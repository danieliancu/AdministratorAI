"""What each kind of import expects, how a row is checked, and what it creates."""

import hashlib
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.utils import timezone

from apps.core.db.scope import current_scope
from apps.core.numbers import BadValue, parse_date, parse_decimal
from apps.expenses import services as expense_services
from apps.expenses.models import Expense
from apps.inventory import services as stock_services
from apps.inventory.models import Product, StockMovement
from apps.sales import services as sales_services
from apps.sales.models import Customer, Invoice, Payment, SaleTransaction

from .models import ImportBatch, Source

OLDEST = date(2000, 1, 1)


class RowInvalid(Exception):
    pass


class RowDuplicate(Exception):
    pass


def fold(text):
    decomposed = unicodedata.normalize("NFKD", str(text))
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "_".join(plain.lower().replace("-", " ").replace(".", " ").split())


def _text(limit):
    def parse(value):
        text = str(value).strip()
        if len(text) > limit:
            raise BadValue(f"Textul depășește {limit} de caractere.")
        return text

    return parse


def _identifier(limit):
    # A number cell such as 1001.0 is still the identifier 1001.
    base = _text(limit)

    def parse(value):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        return base(value)

    return parse


def _money(value):
    return parse_decimal(value, places=2)


def _quantity(value):
    return parse_decimal(value, places=3)


def _date(value):
    parsed = parse_date(value)
    if not OLDEST <= parsed <= timezone.localdate() + timedelta(days=366):
        raise BadValue(f"Data {parsed:%d.%m.%Y} nu este plauzibilă.")
    return parsed


@dataclass(frozen=True)
class Column:
    key: str
    label: str
    parse: object
    required: bool = False
    aliases: tuple = ()


@dataclass
class Context:
    """State of one pass over a file. A preview counts earlier rows; a commit sees the database."""

    previewing: bool
    seen: set = field(default_factory=set)
    paid: dict = field(default_factory=dict)
    stock: dict = field(default_factory=dict)


def fingerprint(kind, *parts):
    joined = "|".join(fold(part) for part in parts)
    return hashlib.sha256(f"{kind}|{joined}".encode()).hexdigest()


def _check_amounts(values):
    net, vat, gross = values["net"], values["vat"], values["gross"]
    if gross <= 0 or net < 0 or vat < 0:
        raise RowInvalid("Sumele negative sau zero, inclusiv stornările, nu sunt încă acceptate.")
    if net + vat != gross:
        raise RowInvalid(f"Totalul {gross} diferă de valoarea fără TVA plus TVA ({net + vat}).")


def _check_currency(values):
    currency = (values.get("currency") or "RON").upper()
    if currency not in ("RON", "LEI"):
        raise RowInvalid(f"Moneda {currency} nu este acceptată: importul primește doar RON.")


_AMOUNT_COLUMNS = (
    Column("net", "net", _money, True, ("valoare", "valoare_fara_tva", "baza", "fara_tva")),
    Column("vat", "tva", _money, True, ("valoare_tva",)),
    Column("gross", "total", _money, True, ("total_cu_tva", "valoare_totala")),
    Column("currency", "moneda", _text(10), False, ("valuta",)),
)


class Spec:
    kind = None
    columns = ()

    def check(self, values, context):
        """Return the row's fingerprint, or raise RowInvalid or RowDuplicate."""
        raise NotImplementedError

    def create(self, values, *, key, batch, user_id):
        """Create the record and return its id."""
        raise NotImplementedError

    def _once(self, key, context, message):
        if key in context.seen:
            raise RowDuplicate(f"{message} (apare de două ori în fișier).")
        context.seen.add(key)


class Customers(Spec):
    kind = ImportBatch.Kind.CUSTOMERS
    columns = (
        Column("name", "denumire", _text(200), True, ("client", "nume", "firma")),
        Column("cui", "cui", _identifier(20), False, ("cod_fiscal", "cif")),
        Column("email", "email", _text(254), False, ("e_mail",)),
        Column("phone", "telefon", _identifier(40), False, ("tel",)),
    )

    def check(self, values, context):
        name, cui = values["name"], values.get("cui", "")
        key = fingerprint(self.kind, cui or name)
        self._once(key, context, f"Clientul {name}")
        known = Customer.objects.filter(cui=cui) if cui else Customer.objects.none()
        if known.exists() or Customer.objects.filter(name__iexact=name, cui__in=["", cui]).exists():
            raise RowDuplicate(f"Clientul {name} există deja.")
        return key

    def create(self, values, *, key, batch, user_id):
        return Customer.objects.create(
            tenant_id=current_scope().tenant_id,
            name=values["name"],
            cui=values.get("cui", ""),
            email=values.get("email", ""),
            phone=values.get("phone", ""),
            source=Source.IMPORT,
            import_batch=batch,
            import_fingerprint=key,
            created_by_id=user_id,
        ).pk


class Invoices(Spec):
    kind = ImportBatch.Kind.INVOICES
    columns = (
        Column("number", "numar", _identifier(60), True, ("numar_factura", "factura", "nr")),
        Column("issue_date", "data", _date, True, ("data_emiterii", "data_factura")),
        Column("due_date", "scadenta", _date, False, ("data_scadenta",)),
        Column("customer", "client", _text(200), True, ("denumire_client",)),
        Column("cui", "cui_client", _identifier(20), False, ("cui", "cod_fiscal")),
        *_AMOUNT_COLUMNS,
        Column("category", "categorie", _text(100)),
        Column("notes", "observatii", _text(500), False, ("note",)),
    )

    def check(self, values, context):
        _check_amounts(values)
        _check_currency(values)
        due = values.get("due_date")
        if due and due < values["issue_date"]:
            raise RowInvalid("Scadența este înaintea datei emiterii.")
        number = values["number"]
        key = fingerprint(self.kind, number)
        self._once(key, context, f"Factura {number}")
        existing = Invoice.objects.filter(number=number).first()
        if existing is not None:
            if existing.gross != values["gross"] or existing.issue_date != values["issue_date"]:
                raise RowInvalid(f"Factura {number} există deja, cu altă dată sau alt total.")
            raise RowDuplicate(f"Factura {number} există deja.")
        return key

    def create(self, values, *, key, batch, user_id):
        customer = sales_services.find_or_create_customer(
            values["customer"],
            values.get("cui", ""),
            user_id=user_id,
            source=Source.IMPORT,
            batch=batch,
        )
        return Invoice.objects.create(
            tenant_id=current_scope().tenant_id,
            number=values["number"],
            customer=customer,
            category=sales_services.category_named(values.get("category")),
            issue_date=values["issue_date"],
            due_date=values.get("due_date"),
            net=values["net"],
            vat=values["vat"],
            gross=values["gross"],
            notes=values.get("notes", ""),
            source=Source.IMPORT,
            import_batch=batch,
            import_fingerprint=key,
            created_by_id=user_id,
        ).pk


class Payments(Spec):
    kind = ImportBatch.Kind.PAYMENTS
    columns = (
        Column("invoice", "numar_factura", _identifier(60), True, ("factura", "numar")),
        Column("date", "data", _date, True, ("data_incasarii",)),
        Column("amount", "suma", _money, True, ("suma_incasata", "valoare")),
        Column("method", "metoda", _text(20), False, ("modalitate",)),
        Column("reference", "referinta", _identifier(100), False, ("document", "extras")),
    )
    _METHODS = {
        "bank": Payment.Method.BANK,
        "banca": Payment.Method.BANK,
        "transfer": Payment.Method.BANK,
        "op": Payment.Method.BANK,
        "numerar": Payment.Method.CASH,
        "cash": Payment.Method.CASH,
        "card": Payment.Method.CARD,
    }

    def _invoice(self, number):
        return Invoice.objects.filter(number=number).first()

    def check(self, values, context):
        if values["amount"] <= 0:
            raise RowInvalid("Suma trebuie să fie mai mare decât zero.")
        method = fold(values.get("method", ""))
        if method and method not in self._METHODS:
            raise RowInvalid(f"Metoda „{values['method']}” nu este recunoscută.")
        number = values["invoice"]
        key = fingerprint(
            self.kind, number, values["date"], values["amount"], values.get("reference", "")
        )
        self._once(key, context, f"Încasarea pentru factura {number}")
        if Payment.objects.filter(import_fingerprint=key).exists():
            raise RowDuplicate(f"Încasarea pentru factura {number} a fost deja importată.")
        invoice = self._invoice(number)
        if invoice is None:
            raise RowInvalid(f"Factura {number} nu există. Importă mai întâi facturile.")
        if invoice.status != Invoice.Status.ISSUED:
            raise RowInvalid(f"Factura {number} este anulată.")
        if context.previewing:
            already = context.paid.get(number)
            if already is None:
                already = sales_services._paid_so_far(invoice.pk)
            if already + values["amount"] > invoice.gross:
                raise RowInvalid(f"Încasările depășesc totalul facturii {number}.")
            context.paid[number] = already + values["amount"]
        return key

    def create(self, values, *, key, batch, user_id):
        try:
            payment = sales_services.record_payment(
                self._invoice(values["invoice"]).pk,
                date=values["date"],
                amount=values["amount"],
                method=self._METHODS.get(fold(values.get("method", "")), Payment.Method.OTHER),
                reference=values.get("reference", ""),
                user_id=user_id,
                source=Source.IMPORT,
                batch=batch,
                fingerprint=key,
            )
        except sales_services.SalesError as exc:
            raise RowInvalid(str(exc)) from exc
        return payment.pk


class Sales(Spec):
    kind = ImportBatch.Kind.SALES
    columns = (
        Column("date", "data", _date, True),
        Column("description", "descriere", _text(200), True, ("denumire", "explicatie")),
        *_AMOUNT_COLUMNS,
        Column("category", "categorie", _text(100)),
        Column("customer", "client", _text(200)),
        Column("reference", "referinta", _identifier(100), False, ("document", "bon", "raport_z")),
    )

    def check(self, values, context):
        _check_amounts(values)
        _check_currency(values)
        key = fingerprint(
            self.kind,
            values["date"],
            values["description"],
            values["gross"],
            values.get("reference", ""),
        )
        self._once(key, context, f"Vânzarea {values['description']}")
        if SaleTransaction.objects.filter(import_fingerprint=key).exists():
            raise RowDuplicate(f"Vânzarea {values['description']} a fost deja importată.")
        return key

    def create(self, values, *, key, batch, user_id):
        customer = None
        if values.get("customer"):
            customer = sales_services.find_or_create_customer(
                values["customer"], user_id=user_id, source=Source.IMPORT, batch=batch
            )
        return SaleTransaction.objects.create(
            tenant_id=current_scope().tenant_id,
            date=values["date"],
            description=values["description"],
            customer=customer,
            category=sales_services.category_named(values.get("category")),
            net=values["net"],
            vat=values["vat"],
            gross=values["gross"],
            reference=values.get("reference", ""),
            source=Source.IMPORT,
            import_batch=batch,
            import_fingerprint=key,
            created_by_id=user_id,
        ).pk


class Expenses(Spec):
    kind = ImportBatch.Kind.EXPENSES
    columns = (
        Column("date", "data", _date, True, ("data_documentului",)),
        Column("supplier", "furnizor", _text(200), True, ("denumire_furnizor",)),
        Column("document_number", "numar_document", _identifier(60), False, ("numar", "document")),
        Column("description", "descriere", _text(200), False, ("explicatie",)),
        Column("category", "categorie", _text(100)),
        *_AMOUNT_COLUMNS,
        Column("paid_date", "data_platii", _date, False, ("platit_la",)),
    )

    def check(self, values, context):
        _check_amounts(values)
        _check_currency(values)
        key = fingerprint(
            self.kind,
            values["date"],
            values["supplier"],
            values.get("document_number", ""),
            values["gross"],
        )
        self._once(key, context, f"Cheltuiala de la {values['supplier']}")
        if Expense.objects.filter(import_fingerprint=key).exists():
            raise RowDuplicate(f"Cheltuiala de la {values['supplier']} a fost deja importată.")
        return key

    def create(self, values, *, key, batch, user_id):
        return Expense.objects.create(
            tenant_id=current_scope().tenant_id,
            date=values["date"],
            supplier=values["supplier"],
            document_number=values.get("document_number", ""),
            description=values.get("description", ""),
            category=expense_services.category_named(values.get("category")),
            net=values["net"],
            vat=values["vat"],
            gross=values["gross"],
            paid_date=values.get("paid_date"),
            source=Source.IMPORT,
            import_batch=batch,
            import_fingerprint=key,
            created_by_id=user_id,
        ).pk


class Products(Spec):
    kind = ImportBatch.Kind.PRODUCTS
    columns = (
        Column("sku", "cod", _identifier(60), True, ("cod_produs", "sku")),
        Column("name", "denumire", _text(200), True, ("produs", "nume")),
        Column("unit", "um", _text(20), False, ("unitate", "unitate_de_masura")),
        Column("threshold", "prag_reaprovizionare", _quantity, False, ("prag", "stoc_minim")),
        Column("unit_cost", "cost_unitar", _money, False, ("cost", "pret_achizitie")),
    )

    def check(self, values, context):
        for name in ("threshold", "unit_cost"):
            if values.get(name) is not None and values[name] < 0:
                raise RowInvalid("Pragul și costul nu pot fi negative.")
        sku = values["sku"]
        key = fingerprint(self.kind, sku)
        self._once(key, context, f"Produsul {sku}")
        if Product.objects.filter(sku=sku).exists():
            raise RowDuplicate(f"Produsul {sku} există deja.")
        return key

    def create(self, values, *, key, batch, user_id):
        return Product.objects.create(
            tenant_id=current_scope().tenant_id,
            sku=values["sku"],
            name=values["name"],
            unit=values.get("unit") or "buc",
            reorder_threshold=values.get("threshold"),
            unit_cost=values.get("unit_cost"),
            source=Source.IMPORT,
            import_batch=batch,
            import_fingerprint=key,
            created_by_id=user_id,
        ).pk


class Movements(Spec):
    kind = ImportBatch.Kind.MOVEMENTS
    columns = (
        Column("sku", "cod_produs", _identifier(60), True, ("cod", "sku")),
        Column("date", "data", _date, True),
        Column("movement", "tip", _text(20), True, ("tip_miscare",)),
        Column("quantity", "cantitate", _quantity, True, ("cant",)),
        Column("reference", "referinta", _identifier(100), False, ("document", "nir")),
    )
    _KINDS = {
        "intrare": StockMovement.Kind.RECEIPT,
        "iesire": StockMovement.Kind.ISSUE,
        "ajustare": StockMovement.Kind.ADJUSTMENT,
    }

    def _kind(self, values):
        kind = self._KINDS.get(fold(values["movement"]))
        if kind is None:
            raise RowInvalid("Tipul trebuie să fie intrare, ieșire sau ajustare.")
        return kind

    def check(self, values, context):
        kind = self._kind(values)
        try:
            signed = stock_services.signed_quantity(kind, values["quantity"])
        except stock_services.StockError as exc:
            raise RowInvalid(str(exc)) from exc
        sku = values["sku"]
        key = fingerprint(
            self.kind, sku, values["date"], kind, values["quantity"], values.get("reference", "")
        )
        self._once(key, context, f"Mișcarea pentru {sku}")
        if StockMovement.objects.filter(import_fingerprint=key).exists():
            raise RowDuplicate(f"Mișcarea pentru {sku} a fost deja importată.")
        product = Product.objects.filter(sku=sku).first()
        if product is None:
            raise RowInvalid(f"Produsul {sku} nu există. Importă mai întâi produsele.")
        if context.previewing:
            level = context.stock.get(sku)
            if level is None:
                level = stock_services.level_of(product.pk)
            if level + signed < Decimal(0):
                raise RowInvalid(f"Stoc insuficient pentru {sku}: sunt disponibile {level}.")
            context.stock[sku] = level + signed
        return key

    def create(self, values, *, key, batch, user_id):
        try:
            movement = stock_services.record_movement(
                Product.objects.get(sku=values["sku"]).pk,
                date=values["date"],
                kind=self._kind(values),
                quantity=values["quantity"],
                reference=values.get("reference", ""),
                user_id=user_id,
                source=Source.IMPORT,
                batch=batch,
                fingerprint=key,
            )
        except stock_services.StockError as exc:
            raise RowInvalid(str(exc)) from exc
        return movement.pk


SPECS = {
    spec.kind: spec
    for spec in (
        Customers(),
        Invoices(),
        Payments(),
        Sales(),
        Expenses(),
        Products(),
        Movements(),
    )
}
