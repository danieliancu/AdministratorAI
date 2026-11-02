"""The pages, through HTTP: labels, roles, isolation between firms and browser-facing safety."""

import uuid
from datetime import date
from decimal import Decimal as D

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from apps.audit.models import TenantEvent
from apps.core.db.scope import db_scope
from apps.expenses.models import Expense, ExpenseDocument
from apps.expenses.services import attach_document
from apps.financial_imports.models import ImportBatch
from apps.financial_imports.services import create_batch
from apps.inventory.models import Product, StockMovement
from apps.sales.models import Customer, Invoice, Payment
from apps.tenants.models import TenantMembership
from apps.tenants.roles import Role
from tests.factories import make_user
from tests.finance.helpers import customer, expense, invoice, product, sale, scope, world

pytestmark = pytest.mark.django_db
PASSWORD = "correct-horse-battery"


def sign_in(client, user):
    response = client.post(
        reverse("public:login"), {"identifier": user.email, "password": PASSWORD}
    )
    assert response.status_code == 302


def url(name, tenant, *args):
    return reverse(f"tenant:{name}", args=[tenant.pk, *args])


def member(tenant, role):
    user = make_user()
    with db_scope(tenant_id=tenant.pk, user_id=tenant.created_by_id):
        TenantMembership.objects.create(tenant=tenant, user=user, role=role)
    return user


@pytest.fixture
def owner(client):
    user, tenant = world()
    sign_in(client, user)
    return user, tenant


def test_empty_dashboard_shows_zeroes_as_zeroes_and_no_chart(client, owner):
    user, tenant = owner
    content = client.get(url("dashboard", tenant)).content.decode()
    assert "Nu există încă date pentru grafic" in content
    assert "<canvas" not in content
    assert "Necunoscută" in content
    assert "Nu este profit contabil" in content
    assert "nu sunt rezultate contabile" in content


def test_dashboard_labels_and_keeps_invoiced_apart_from_received(client, owner):
    user, tenant = owner
    today = date.today().replace(day=1)
    with scope(user, tenant):
        invoice(tenant, "F1", issue_date=today)
    content = client.get(url("dashboard", tenant)).content.decode()
    assert "Nu înseamnă bani primiți" in content
    assert "119,00 lei" in content
    assert "<canvas" in content and "chart-data" in content


def test_dashboard_month_selector_tolerates_nonsense(client, owner):
    user, tenant = owner
    for value in ("2026-13", "abc", "1-1", "99999-01", "2026-02-30", ""):
        assert client.get(url("dashboard", tenant), {"luna": value}).status_code == 200


def test_manual_invoice_flow_and_audit(client, owner):
    user, tenant = owner
    with scope(user, tenant):
        buyer = customer(tenant)
    response = client.post(
        url("invoice-new", tenant),
        {
            "number": "F100",
            "customer": buyer.pk,
            "issue_date": "2026-03-10",
            "net": "1.000,00",
            "vat": "190,00",
            "gross": "1.190,00",
            "category_name": "Servicii",
        },
    )
    assert response.status_code == 302
    with scope(user, tenant):
        created = Invoice.objects.get(number="F100")
        assert created.gross == D("1190.00") and created.category.name == "Servicii"
        assert created.source == "manual" and created.created_by_id == user.pk
        assert TenantEvent.objects.filter(action="invoice.created").exists()

    detail = url("invoice-detail", tenant, created.pk)
    assert (
        client.post(detail, {"date": "2026-03-11", "amount": "2000", "method": "bank"}).status_code
        == 200
    )
    with scope(user, tenant):
        assert not Payment.objects.exists()
    assert (
        client.post(detail, {"date": "2026-03-11", "amount": "190", "method": "bank"}).status_code
        == 302
    )
    with scope(user, tenant):
        assert Payment.objects.get().amount == D("190.00")

    edited = client.post(
        url("invoice-edit", tenant, created.pk),
        {
            "number": "F100",
            "customer": buyer.pk,
            "issue_date": "2026-03-10",
            "net": "100,00",
            "vat": "19,00",
            "gross": "119,00",
        },
    )
    assert edited.status_code == 200 and "deja încasată" in edited.content.decode()


@pytest.mark.parametrize(
    "net,vat,gross,message",
    [
        ("100", "19", "120", "egal cu valoarea"),
        ("-100", "19", "-81", "negative"),
        ("1.234", "0", "1.234", "ambiguu"),
    ],
)
def test_form_explains_wrong_amounts(client, owner, net, vat, gross, message):
    user, tenant = owner
    with scope(user, tenant):
        buyer = customer(tenant)
    response = client.post(
        url("invoice-new", tenant),
        {
            "number": "F1",
            "customer": buyer.pk,
            "issue_date": "2026-03-10",
            "net": net,
            "vat": vat,
            "gross": gross,
        },
    )
    assert response.status_code == 200
    assert message in response.content.decode()


def test_duplicate_invoice_number_is_a_form_error(client, owner):
    user, tenant = owner
    with scope(user, tenant):
        buyer = customer(tenant)
        invoice(tenant, "F1")
    response = client.post(
        url("invoice-new", tenant),
        {
            "number": "F1",
            "customer": buyer.pk,
            "issue_date": "2026-03-10",
            "net": "1",
            "vat": "0",
            "gross": "1",
        },
    )
    assert response.status_code == 200 and "Există deja" in response.content.decode()


def test_expense_sale_and_product_flows(client, owner):
    user, tenant = owner
    assert (
        client.post(
            url("expense-new", tenant),
            {
                "date": "2026-03-10",
                "supplier": "Enel",
                "net": "10",
                "vat": "0",
                "gross": "10",
                "category_name": "Utilități",
            },
        ).status_code
        == 302
    )
    assert (
        client.post(
            url("sale-new", tenant),
            {"date": "2026-03-10", "description": "Z", "net": "10", "vat": "0", "gross": "10"},
        ).status_code
        == 302
    )
    assert (
        client.post(
            url("product-new", tenant),
            {"sku": "A", "name": "Mere", "unit": "kg", "is_active": "on"},
        ).status_code
        == 302
    )
    with scope(user, tenant):
        item = Product.objects.get()
    page = url("product-detail", tenant, item.pk)
    assert (
        client.post(page, {"date": "2026-03-10", "kind": "issue", "quantity": "1"}).status_code
        == 200
    )
    assert (
        client.post(page, {"date": "2026-03-10", "kind": "receipt", "quantity": "2,5"}).status_code
        == 302
    )
    with scope(user, tenant):
        assert StockMovement.objects.get().quantity == D("2.500")
        assert Expense.objects.get().category.name == "Utilități"


def test_lists_search_and_htmx_returns_only_the_table(client, owner):
    user, tenant = owner
    with scope(user, tenant):
        invoice(tenant, "ALFA1")
        invoice(tenant, "BETA2")
    response = client.get(
        url("invoice-list", tenant), {"q": "alfa"}, headers={"HX-Request": "true"}
    )
    content = response.content.decode()
    assert "ALFA1" in content and "BETA2" not in content and "<html" not in content


def test_pagination_keeps_filters(client, owner):
    user, tenant = owner
    with scope(user, tenant):
        buyer = customer(tenant)
        for number in range(30):
            invoice(tenant, f"F{number}", customer=buyer)
    content = client.get(url("invoice-list", tenant), {"stare": "issued"}).content.decode()
    assert "?pagina=2&amp;stare=issued" in content


def test_import_flow_through_pages(client, owner):
    user, tenant = owner
    upload = SimpleUploadedFile(
        "cheltuieli.csv",
        b"data;furnizor;net;tva;total\n10.03.2026;Enel;10;0;10\n10.03.2026;Rau;10;0;11\n",
    )
    response = client.post(url("import-list", tenant), {"kind": "expenses", "file": upload})
    assert response.status_code == 302
    detail = response["Location"]
    content = client.get(detail).content.decode()
    assert "Nu dovedește că datele contabile" in content
    assert "10.03.2026 · Enel · 10 · 0 · 10" in content
    with scope(user, tenant):
        batch = ImportBatch.objects.get()
        assert not Expense.objects.exists()
    rejected = client.get(url("import-rejected", tenant, batch.pk))
    assert "Rau" in rejected.content.decode() and "Eroare" in rejected.content.decode()
    assert client.post(url("import-commit", tenant, batch.pk)).status_code == 302
    with scope(user, tenant):
        assert Expense.objects.get().source == "import"


def test_bad_upload_explains_and_stores_nothing(client, owner):
    user, tenant = owner
    upload = SimpleUploadedFile("a.csv", b"data;furnizor\n1;2\n")
    response = client.post(url("import-list", tenant), {"kind": "expenses", "file": upload})
    assert response.status_code == 200 and "Lipsesc coloanele" in response.content.decode()
    with scope(user, tenant):
        assert not ImportBatch.objects.exists()


def test_template_download_has_no_invented_data(client, owner):
    user, tenant = owner
    content = client.get(url("import-template", tenant, "invoices")).content.decode()
    assert len(content.strip().splitlines()) == 1 and "numar;data" in content
    assert client.get(url("import-template", tenant, "nimic")).status_code == 404


def test_rejected_rows_cannot_smuggle_a_formula(client, owner):
    user, tenant = owner
    with scope(user, tenant):
        batch, _ = create_batch(
            "expenses",
            "a.csv",
            b'data;furnizor;net;tva;total\n=cmd();=HYPERLINK("x");1;0;9\n',
            user_id=user.pk,
        )
    content = client.get(url("import-rejected", tenant, batch.pk)).content.decode()
    assert "'=cmd()" in content and "\n=cmd" not in content


@pytest.mark.parametrize(
    "name",
    ["report-summary", "report-sales", "report-expenses", "report-receivables", "report-inventory"],
)
def test_reports_render_empty_and_with_data_and_export(client, owner, name):
    user, tenant = owner
    assert client.get(url(name, tenant)).status_code == 200
    with scope(user, tenant):
        invoice(tenant, "F1", issue_date=date.today())
        sale(tenant, on=date.today())
        expense(tenant, on=date.today())
        product(tenant, "A", unit_cost=D("1.00"))
    assert client.get(url(name, tenant)).status_code == 200
    exported = client.get(url(name, tenant), {"export": "csv"})
    assert exported.status_code == 200 and exported["Content-Type"].startswith("text/csv")
    assert exported["Content-Disposition"].startswith("attachment")


def test_report_period_rejects_nonsense(client, owner):
    user, tenant = owner
    for query in ({"de_la": "x", "pana_la": "y"}, {"de_la": "2026-03-10", "pana_la": "2026-03-01"}):
        assert client.get(url("report-summary", tenant), query).status_code == 200


def test_summary_never_calls_the_estimate_profit(client, owner):
    user, tenant = owner
    content = client.get(url("report-summary", tenant)).content.decode()
    assert "Rezultat estimat înainte de impozite" in content
    assert "Nu este profit contabil" in content
    assert "Calculat doar din datele introduse" in content


def test_opening_cash_is_declared_once_and_audited(client, owner):
    user, tenant = owner
    page = url("opening-cash", tenant)
    assert client.post(page, {"amount": "1.000,50", "as_of": "2026-03-01"}).status_code == 302
    assert client.post(page, {"amount": "2000", "as_of": "2026-03-02"}).status_code == 302
    future = client.post(page, {"amount": "1", "as_of": "2999-01-01"})
    assert future.status_code == 200
    with scope(user, tenant):
        assert TenantEvent.objects.filter(action="cash.opening_declared").count() == 2


def test_document_download_is_always_an_attachment(client, owner, settings, tmp_path):
    settings.TENANT_FILE_ROOT = str(tmp_path)
    user, tenant = owner
    with scope(user, tenant):
        record = expense(tenant)
    page = url("expense-detail", tenant, record.pk)
    refused = SimpleUploadedFile("x.pdf", b"<html><script>alert(1)</script>", "application/pdf")
    assert "doar fișiere" in client.post(page, {"file": refused}).content.decode()
    good = SimpleUploadedFile("<x>.pdf", b"%PDF-1.7", "text/html")
    assert client.post(page, {"file": good}).status_code == 302
    with scope(user, tenant):
        document = ExpenseDocument.objects.get()
    response = client.get(url("document-download", tenant, document.pk))
    assert response.content == b"%PDF-1.7"
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"].startswith("attachment")
    assert response["X-Content-Type-Options"] == "nosniff"


VIEWS = [
    "invoice-list",
    "sale-list",
    "customer-list",
    "expense-list",
    "recurring-list",
    "product-list",
    "import-list",
    "report-summary",
]
EDITS = ["invoice-new", "sale-new", "customer-new", "expense-new", "recurring-new", "product-new"]


@pytest.mark.parametrize("name", VIEWS)
def test_read_only_can_view(client, name):
    _, tenant = world()
    sign_in(client, member(tenant, Role.READ_ONLY))
    assert client.get(url(name, tenant)).status_code == 200


@pytest.mark.parametrize("name", EDITS)
def test_read_only_cannot_open_edit_pages(client, name):
    _, tenant = world()
    sign_in(client, member(tenant, Role.READ_ONLY))
    assert client.get(url(name, tenant)).status_code == 403


def test_read_only_cannot_write_through_detail_pages(client):
    owner_user, tenant = world()
    with scope(owner_user, tenant):
        bill = invoice(tenant)
        item = product(tenant)
        record = expense(tenant)
    sign_in(client, member(tenant, Role.READ_ONLY))
    assert (
        client.post(
            url("invoice-detail", tenant, bill.pk),
            {"date": "2026-03-11", "amount": "1", "method": "bank"},
        ).status_code
        == 404
    )
    assert (
        client.post(
            url("product-detail", tenant, item.pk),
            {"date": "2026-03-11", "kind": "receipt", "quantity": "1"},
        ).status_code
        == 404
    )
    assert client.post(url("expense-detail", tenant, record.pk), {}).status_code == 404
    assert client.post(url("invoice-cancel", tenant, bill.pk)).status_code == 403
    with scope(owner_user, tenant):
        assert not Payment.objects.exists() and not StockMovement.objects.exists()


def test_member_can_record_but_not_import(client):
    _, tenant = world()
    sign_in(client, member(tenant, Role.MEMBER))
    assert client.get(url("invoice-new", tenant)).status_code == 200
    upload = SimpleUploadedFile("a.csv", b"data;furnizor;net;tva;total\n10.03.2026;A;1;0;1\n")
    assert (
        client.post(url("import-list", tenant), {"kind": "expenses", "file": upload}).status_code
        == 404
    )


def test_accountant_can_import(client):
    _, tenant = world()
    sign_in(client, member(tenant, Role.ACCOUNTANT))
    upload = SimpleUploadedFile("a.csv", b"data;furnizor;net;tva;total\n10.03.2026;A;1;0;1\n")
    assert (
        client.post(url("import-list", tenant), {"kind": "expenses", "file": upload}).status_code
        == 302
    )


def test_another_firms_records_answer_like_missing_ones(client, owner):
    user, tenant = owner
    bob, other = world()
    with scope(bob, other):
        bill = invoice(other)
        record = expense(other)
        item = product(other)
        buyer = Customer.objects.first()
        payment = Payment.objects.create(
            tenant=other, invoice=bill, date=date(2026, 3, 1), amount=D("1")
        )
        attached = ExpenseDocument.objects.create(
            tenant=other,
            expense=record,
            original_name="a.pdf",
            content_type="application/pdf",
            size=1,
            file_key=f"{other.pk}/aa/x",
            sha256="x",
        )
        batch, _ = create_batch(
            "sales", "a.csv", b"data;descriere;net;tva;total\n1;2;3;4;5\n", user_id=bob.pk
        )

    for name, target in (
        ("invoice-detail", bill.pk),
        ("invoice-edit", bill.pk),
        ("customer-edit", buyer.pk),
        ("expense-detail", record.pk),
        ("expense-edit", record.pk),
        ("document-download", attached.pk),
        ("product-detail", item.pk),
        ("product-edit", item.pk),
        ("import-detail", batch.pk),
        ("import-rejected", batch.pk),
    ):
        assert client.get(url(name, tenant, target)).status_code == 404, name
    for name, target in (
        ("invoice-cancel", bill.pk),
        ("payment-void", payment.pk),
        ("expense-void", record.pk),
        ("import-commit", batch.pk),
        ("import-discard", batch.pk),
    ):
        assert client.post(url(name, tenant, target)).status_code == 404, name
    assert client.get(url("invoice-detail", tenant, uuid.uuid4())).status_code == 404


def test_another_firms_customer_cannot_be_chosen(client, owner):
    user, tenant = owner
    bob, other = world()
    with scope(bob, other):
        foreign = customer(other)
    response = client.post(
        url("invoice-new", tenant),
        {
            "number": "F1",
            "customer": foreign.pk,
            "issue_date": "2026-03-10",
            "net": "1",
            "vat": "0",
            "gross": "1",
        },
    )
    assert response.status_code == 200
    with scope(user, tenant):
        assert not Invoice.objects.exists()


def test_figures_never_include_another_firm(client, owner):
    user, tenant = owner
    bob, other = world()
    with scope(bob, other):
        invoice(other, "SECRET", net="777.00", vat="0.00", gross="777.00", issue_date=date.today())
    assert "777" not in client.get(url("dashboard", tenant)).content.decode()
    assert "SECRET" not in client.get(url("invoice-list", tenant)).content.decode()
    assert "777" not in client.get(url("report-summary", tenant)).content.decode()


def test_attach_document_helper_stays_under_its_tenant(settings, tmp_path):
    settings.TENANT_FILE_ROOT = str(tmp_path)
    user, tenant = world()
    with scope(user, tenant):
        document = attach_document(
            expense(tenant), name="a.pdf", content=b"%PDF-1", user_id=user.pk
        )
    assert document.file_key.startswith(f"{tenant.pk}/")
