"""The firm's figures, calculated by the application. The model only receives them.

Only the sections a question needs are gathered, so no more company data than necessary
reaches the AI provider.
"""

from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from apps.core.templatetags.money import lei, quantity
from apps.inventory.models import StockMovement
from apps.inventory.services import low_stock
from apps.reports import figures


class FactList:
    def __init__(self):
        self.items = []

    def _add(self, label, value, note=""):
        self.items.append(
            {"id": f"F{len(self.items) + 1}", "label": label, "value": value, "note": note}
        )

    def money(self, label, amount, note=""):
        self._add(label, lei(amount), note)

    def count(self, label, amount, note=""):
        self._add(label, str(amount), note)

    def qty(self, label, amount, note=""):
        self._add(label, quantity(amount), note)

    def text(self, label, value, note=""):
        self._add(label, value, note)

    def change(self, label, change):
        self.money(f"{label}: perioada anterioară", change["previous"])
        self.money(f"{label}: diferență față de perioada anterioară", change["difference"])
        if change["percent"] is not None:
            self.text(f"{label}: variație procentuală", f"{change['percent']}%".replace(".", ","))


def _summary(facts, start, end, as_of):
    current = figures.period_figures(start, end)
    previous_start, previous_end = figures.previous_period(start, end)
    previous = figures.period_figures(previous_start, previous_end)
    facts.text(
        "Perioada anterioară folosită la comparații",
        f"{previous_start:%d.%m.%Y} – {previous_end:%d.%m.%Y}",
    )
    facts.money(
        "Venituri înregistrate, fără TVA",
        current.revenue_net,
        "Facturi și vânzări fără factură, la data documentului. Nu sunt bani primiți.",
    )
    facts.change("Venituri înregistrate", figures.change(current.revenue_net, previous.revenue_net))
    facts.money("Facturat, cu TVA", current.invoiced_gross)
    facts.count("Facturi emise", current.invoice_count)
    facts.money("Încasat", current.received_total, "Bani primiți, din încasările înregistrate.")
    facts.change("Încasat", figures.change(current.received_total, previous.received_total))
    facts.money("Cheltuieli înregistrate, fără TVA", current.expenses_net)
    facts.change(
        "Cheltuieli înregistrate", figures.change(current.expenses_net, previous.expenses_net)
    )
    facts.count("Documente de cheltuieli", current.expense_count)
    facts.money("Cheltuieli plătite", current.expenses_paid)
    facts.money(
        "Rezultat estimat înainte de impozite",
        current.estimated_result,
        "Venituri minus cheltuieli, fără TVA. Nu este profit contabil.",
    )
    facts.money(f"Facturi neîncasate la {as_of:%d.%m.%Y}, cu TVA", figures.outstanding(as_of))
    cash = figures.cash_position(as_of)
    if cash is None:
        facts.text("Poziție de numerar estimată", "necunoscută", "Soldul inițial nu este declarat.")
    else:
        facts.money(
            "Poziție de numerar estimată",
            cash.amount,
            f"Sold declarat la {cash.opening_date:%d.%m.%Y}, plus încasări, minus plăți.",
        )


def _expenses(facts, start, end):
    previous_start, previous_end = figures.previous_period(start, end)
    before = dict(figures.expenses_by_category(previous_start, previous_end))
    for name, total in figures.expenses_by_category(start, end)[:10]:
        facts.money(f"Cheltuieli pe categoria {name}, fără TVA", total)
        facts.change(f"Categoria {name}", figures.change(total, before.get(name, Decimal("0.00"))))
    for row in figures.top_suppliers(start, end, limit=5):
        facts.money(f"Cheltuieli la furnizorul {row['supplier']}, fără TVA", row["net"])


def _receivables(facts, today):
    report = figures.aging(today)
    for bucket in report["buckets"]:
        facts.money(f"Neîncasat, {bucket['label']}", bucket["total"], f"{bucket['count']} facturi")
    overdue = [i for i in report["invoices"] if i.days_overdue > 0]
    facts.count("Facturi cu scadența depășită", len(overdue))
    for invoice in sorted(overdue, key=lambda i: i.remaining, reverse=True)[:10]:
        facts.money(
            f"Factura {invoice.number}, client {invoice.customer.name}: rest de încasat",
            invoice.remaining,
            f"Scadentă la {invoice.due_date:%d.%m.%Y}, cu {invoice.days_overdue} zile întârziere.",
        )


def _sales(facts, start, end):
    for name, total in figures.sales_by_category(start, end)[:10]:
        facts.money(f"Vânzări pe categoria {name}, fără TVA", total)
    for row in figures.top_customers(start, end, limit=5):
        facts.money(f"Facturat clientului {row['customer__name']}, fără TVA", row["net"])


def _inventory(facts, start, end):
    for product in low_stock()[:10]:
        facts.qty(
            f"Stoc redus la {product.sku} {product.name} ({product.unit})",
            product.stock,
            f"Prag de reaprovizionare: {quantity(product.reorder_threshold)}.",
        )
    issued = (
        StockMovement.objects.filter(date__range=(start, end), kind=StockMovement.Kind.ISSUE)
        .order_by()
        .values("product__sku", "product__name", "product__unit")
        .annotate(total=Sum("quantity"))
        .order_by("total")[:5]
    )
    for row in issued:
        facts.qty(
            f"Ieșiri din stoc pentru {row['product__sku']} {row['product__name']} "
            f"({row['product__unit']})",
            abs(row["total"]),
            "Ieșiri de stoc, nu vânzări: facturile nu au încă linii pe produse.",
        )
    report = figures.inventory_report(start, end)
    facts.money(
        "Valoare estimată a stocului",
        report["value"],
        "Cantitate înmulțită cu costul declarat. Nu este o evaluare contabilă.",
    )


def build_facts(understanding):
    facts = FactList()
    start, end = understanding.start, understanding.end
    today = timezone.localdate()
    _summary(facts, start, end, min(end, today))
    if "expenses" in understanding.sections:
        _expenses(facts, start, end)
    if "receivables" in understanding.sections:
        _receivables(facts, today)
    if "sales" in understanding.sections:
        _sales(facts, start, end)
    if "inventory" in understanding.sections:
        _inventory(facts, start, end)
    return facts.items
