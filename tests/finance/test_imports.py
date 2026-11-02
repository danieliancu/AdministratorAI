import io
import zipfile
from datetime import date, datetime
from decimal import Decimal as D

import pytest
from openpyxl import Workbook

from apps.core import filestore
from apps.expenses.models import Expense
from apps.financial_imports.models import ImportBatch, ImportRow
from apps.financial_imports.parsing import MAX_ROWS, ImportFileError, read_table
from apps.financial_imports.services import commit_batch, create_batch, discard_batch
from apps.inventory.models import Product, StockMovement
from apps.inventory.services import level_of
from apps.sales.models import Customer, Payment, SaleTransaction
from tests.finance.helpers import invoice, scope, world

pytestmark = pytest.mark.django_db

EXPENSES = """data;furnizor;numar_document;categorie;net;tva;total
10.03.2026;Enel;A1;Utilități;100,00;19,00;119,00
11.03.2026;Orange;B2;Telefon;50,00;9,50;59,50
12.03.2026;Greșit;C3;Telefon;50,00;9,50;60,00
ieri;Fără dată;D4;;1,00;0,00;1,00
10.03.2026;Enel;A1;Utilități;100,00;19,00;119,00
"""


def upload(user, kind, text, name="fisier.csv"):
    content = text if isinstance(text, bytes) else text.encode()
    batch, _created = create_batch(kind, name, content, user_id=user.pk)
    return batch


def statuses(batch):
    return list(
        ImportRow.objects.filter(batch=batch).order_by("number").values_list("status", flat=True)
    )


def test_preview_classifies_rows_and_saves_no_records():
    user, tenant = world()
    with scope(user, tenant):
        batch = upload(user, "expenses", EXPENSES)
        assert statuses(batch) == ["valid", "valid", "invalid", "invalid", "duplicate"]
        assert (batch.total_rows, batch.valid_rows, batch.invalid_rows, batch.duplicate_rows) == (
            5,
            2,
            2,
            1,
        )
        assert Expense.objects.count() == 0
        problems = ImportRow.objects.filter(batch=batch, status="invalid").order_by("number")
        assert "diferă" in problems[0].errors[0]
        assert "dată validă" in problems[1].errors[0]


def test_commit_creates_only_valid_rows_with_provenance():
    user, tenant = world()
    with scope(user, tenant):
        batch = upload(user, "expenses", EXPENSES)
        batch = commit_batch(batch.pk, user_id=user.pk)
        assert batch.status == "committed" and batch.imported_rows == 2
        record = Expense.objects.get(document_number="A1")
        assert record.source == "import" and record.import_batch_id == batch.pk
        assert record.gross == D("119.00") and record.category.name == "Utilități"
        row = ImportRow.objects.get(batch=batch, target_id=record.pk)
        assert row.raw["furnizor"] == "Enel" and row.raw["net"] == "100,00"


def test_same_file_twice_returns_the_first_batch():
    user, tenant = world()
    with scope(user, tenant):
        first, created = create_batch("expenses", "a.csv", EXPENSES.encode(), user_id=user.pk)
        again, created_again = create_batch("expenses", "b.csv", EXPENSES.encode(), user_id=user.pk)
        assert created and not created_again and first.pk == again.pk


def test_committing_twice_changes_nothing():
    user, tenant = world()
    with scope(user, tenant):
        batch = upload(user, "expenses", EXPENSES)
        commit_batch(batch.pk, user_id=user.pk)
        commit_batch(batch.pk, user_id=user.pk)
        assert Expense.objects.count() == 2


def test_overlapping_file_detects_rows_already_imported():
    user, tenant = world()
    header = "data;furnizor;numar_document;net;tva;total\n"
    with scope(user, tenant):
        commit_batch(
            upload(user, "expenses", header + "10.03.2026;Enel;A1;100;19;119\n").pk,
            user_id=user.pk,
        )
        second = upload(
            user,
            "expenses",
            header + "10.03.2026;ENEL;A1;100,00;19,00;119,00\n11.03.2026;Enel;A2;10;0;10\n",
        )
        assert statuses(second) == ["duplicate", "valid"]
        commit_batch(second.pk, user_id=user.pk)
        assert Expense.objects.count() == 2


def test_a_corrected_file_recovers_the_rejected_rows():
    user, tenant = world()
    header = "data;furnizor;numar_document;net;tva;total\n"
    with scope(user, tenant):
        first = upload(
            user, "expenses", header + "10.03.2026;A;1;10;0;10\n10.03.2026;B;2;10;0;11\n"
        )
        commit_batch(first.pk, user_id=user.pk)
        second = upload(
            user, "expenses", header + "10.03.2026;A;1;10;0;10\n10.03.2026;B;2;10;0;10\n"
        )
        assert statuses(second) == ["duplicate", "valid"]
        commit_batch(second.pk, user_id=user.pk)
        assert Expense.objects.count() == 2


def test_discarding_lets_the_same_file_be_uploaded_again():
    user, tenant = world()
    with scope(user, tenant):
        batch = upload(user, "expenses", EXPENSES)
        assert discard_batch(batch.pk, user_id=user.pk).status == "discarded"
        assert commit_batch(batch.pk, user_id=user.pk).status == "discarded"
        assert Expense.objects.count() == 0
        assert upload(user, "expenses", EXPENSES).pk != batch.pk


def test_a_row_that_became_invalid_after_preview_fails_alone():
    user, tenant = world()
    with scope(user, tenant):
        bill = invoice(tenant, "F1")
        batch = upload(
            user,
            "payments",
            "numar_factura;data;suma;referinta\nF1;11.03.2026;100;a\nF1;12.03.2026;19;b\n",
        )
        assert statuses(batch) == ["valid", "valid"]
        Payment.objects.create(
            tenant=tenant, invoice=bill, date=date(2026, 3, 10), amount=D("50.00")
        )
        batch = commit_batch(batch.pk, user_id=user.pk)
        assert statuses(batch) == ["failed", "imported"]
        assert Payment.objects.filter(voided_at__isnull=True).count() == 2


def test_invoices_customers_and_conflicts():
    user, tenant = world()
    header = "numar;data;scadenta;client;cui_client;net;tva;total;moneda\n"
    with scope(user, tenant):
        first = upload(
            user,
            "invoices",
            header
            + "F1;10.03.2026;20.03.2026;Alfa SRL;RO1;100;19;119;RON\n"
            + "F2;10.03.2026;;Alfa SRL;RO1;200;38;238;\n"
            + "F3;10.03.2026;;Beta;;10;0;10;EUR\n"
            + "F4;10.03.2026;01.03.2026;Beta;;10;0;10;\n"
            + "F5;10.03.2026;;Beta;;-10;0;-10;\n",
        )
        assert statuses(first) == ["valid", "valid", "invalid", "invalid", "invalid"]
        commit_batch(first.pk, user_id=user.pk)
        assert Customer.objects.count() == 1
        second = upload(
            user,
            "invoices",
            header
            + "F1;10.03.2026;;Alfa SRL;RO1;100;19;119;\n"
            + "F2;10.03.2026;;Alfa SRL;RO1;300;57;357;\n",
        )
        assert statuses(second) == ["duplicate", "invalid"]
        assert "alt total" in ImportRow.objects.get(batch=second, number=3).errors[0]


def test_payments_preview_counts_earlier_rows_of_the_file():
    user, tenant = world()
    with scope(user, tenant):
        invoice(tenant, "F1")
        batch = upload(
            user,
            "payments",
            "numar_factura;data;suma;metoda;referinta\n"
            "F1;11.03.2026;100;banca;a\n"
            "F1;12.03.2026;100;numerar;b\n"
            "F9;12.03.2026;1;;c\n"
            "F1;12.03.2026;1;troc;d\n",
        )
        assert statuses(batch) == ["valid", "invalid", "invalid", "invalid"]
        commit_batch(batch.pk, user_id=user.pk)
        assert Payment.objects.get().method == "bank"


def test_sales_products_and_movements():
    user, tenant = world()
    with scope(user, tenant):
        sale_batch = upload(
            user,
            "sales",
            "data;descriere;net;tva;total;referinta\n"
            "01.03.2026;Raport Z;100;19;119;Z1\n"
            "01.03.2026;Raport Z;100;19;119;Z2\n"
            "01.03.2026;Raport Z;100;19;119;Z1\n",
        )
        assert statuses(sale_batch) == ["valid", "valid", "duplicate"]
        commit_batch(sale_batch.pk, user_id=user.pk)
        assert SaleTransaction.objects.count() == 2

        product_batch = upload(
            user,
            "products",
            "cod;denumire;um;prag;cost\nA;Mere;kg;5;2,50\nA;Mere;kg;5;2,50\nB;Pere;;;\n",
        )
        assert statuses(product_batch) == ["valid", "duplicate", "valid"]
        commit_batch(product_batch.pk, user_id=user.pk)
        assert Product.objects.get(sku="B").unit == "buc"

        moves = upload(
            user,
            "movements",
            "cod_produs;data;tip;cantitate;referinta\n"
            "A;01.03.2026;intrare;10;n1\n"
            "A;02.03.2026;ieșire;4;n2\n"
            "A;03.03.2026;Iesire;7;n3\n"
            "A;04.03.2026;ajustare;-1;n4\n"
            "Z;04.03.2026;intrare;1;n5\n"
            "A;04.03.2026;mutare;1;n6\n",
        )
        assert statuses(moves) == ["valid", "valid", "invalid", "valid", "invalid", "invalid"]
        commit_batch(moves.pk, user_id=user.pk)
        assert level_of(Product.objects.get(sku="A").pk) == D("5.000")
        assert StockMovement.objects.filter(kind="issue").get().quantity == D("-4.000")


def _xlsx(rows):
    book = Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def test_excel_numbers_and_dates_keep_their_meaning():
    user, tenant = world()
    content = _xlsx(
        [
            ["Data", "Furnizor", "Număr document", "Net", "TVA", "Total"],
            [datetime(2026, 3, 10), "Enel", 1001, 1234.5, 234.56, 1469.06],
            [None, None, None, None, None, None],
            [date(2026, 3, 11), "Orange", "B2", 1.234, 0, 1.234],
        ]
    )
    with scope(user, tenant):
        batch, _ = create_batch("expenses", "date.xlsx", content, user_id=user.pk)
        assert statuses(batch) == ["valid", "invalid"]
        commit_batch(batch.pk, user_id=user.pk)
        record = Expense.objects.get()
        assert record.date == date(2026, 3, 10)
        assert record.net == D("1234.50") and record.gross == D("1469.06")
        assert record.document_number == "1001"


def test_headers_tolerate_case_diacritics_and_aliases():
    user, tenant = world()
    with scope(user, tenant):
        batch = upload(
            user,
            "expenses",
            "DATA;Furnizor;Număr Document;Valoare fără TVA;Valoare TVA;Total cu TVA;Altceva\n"
            "10.03.2026;Enel;A1;10;0;10;x\n",
        )
        assert statuses(batch) == ["valid"]
        assert ImportRow.objects.get(batch=batch).raw["Altceva"] == "x"


def test_windows_1250_files_are_read():
    user, tenant = world()
    text = "data;furnizor;net;tva;total\n10.03.2026;Societatea Şoim;10;0;10\n"
    with scope(user, tenant):
        batch = upload(user, "expenses", text.encode("cp1250"))
        commit_batch(batch.pk, user_id=user.pk)
        assert Expense.objects.get().supplier == "Societatea Şoim"


@pytest.mark.parametrize(
    "name,content,message",
    [
        ("a.txt", b"x", "doar fișiere"),
        ("a.csv", b"", "gol"),
        ("a.csv", b"data;furnizor\n", "niciun rând"),
        ("a.xlsx", b"not a zip", "Excel"),
        ("a.csv", b"a" * (5 * 1024 * 1024 + 1), "5 MB"),
    ],
)
def test_bad_files_are_refused_with_an_explanation(name, content, message):
    with pytest.raises(ImportFileError, match=message):
        read_table(name, content)


def test_missing_required_columns_refuse_the_whole_file():
    user, tenant = world()
    with pytest.raises(ImportFileError, match="total"), scope(user, tenant):
        upload(user, "expenses", "data;furnizor;net;tva\n10.03.2026;A;1;0\n")


def test_row_limit():
    text = "data\n" + "1\n" * (MAX_ROWS + 1)
    with pytest.raises(ImportFileError, match="rânduri"):
        read_table("a.csv", text.encode())


def test_decompression_bomb_is_refused_before_parsing():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/worksheets/sheet1.xml", b"0" * (101 * 1024 * 1024))
    with pytest.raises(ImportFileError, match="prea mare"):
        read_table("a.xlsx", buffer.getvalue())


def test_original_file_is_kept_under_its_tenant():
    user, tenant = world()
    other_user, other = world()
    with scope(user, tenant):
        batch = upload(user, "expenses", EXPENSES)
    assert filestore.get(tenant.pk, batch.file_key) == EXPENSES.encode()
    with pytest.raises(PermissionError):
        filestore.get(other.pk, batch.file_key)


def test_the_same_file_in_two_firms_stays_separate():
    alice, tenant_a = world()
    bob, tenant_b = world()
    with scope(alice, tenant_a):
        batch_a = upload(alice, "expenses", EXPENSES)
        commit_batch(batch_a.pk, user_id=alice.pk)
    with scope(bob, tenant_b):
        batch_b = upload(bob, "expenses", EXPENSES)
        assert batch_a.pk != batch_b.pk
        assert batch_b.valid_rows == 2
        assert not ImportBatch.objects.filter(pk=batch_a.pk).exists()
