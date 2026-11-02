"""Rules that protect financial records, including the ones only the database can enforce."""

from datetime import date
from decimal import Decimal as D

import pytest
from django.db import DatabaseError, IntegrityError, connection, transaction

from apps.expenses import services as expense_services
from apps.expenses.models import Expense, RecurringExpense
from apps.financial_imports.models import ImportBatch, ImportRow
from apps.inventory import services as stock_services
from apps.inventory.models import StockMovement
from apps.sales import services as sales_services
from apps.sales.models import Invoice
from tests.finance.helpers import customer, expense, invoice, product, scope, world

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize(
    "net,vat,gross",
    [("100.00", "19.00", "120.00"), ("-1.00", "1.00", "0.00"), ("0.00", "0.00", "0.00")],
)
def test_database_refuses_amounts_that_do_not_add_up(net, vat, gross):
    user, tenant = world()
    with pytest.raises(IntegrityError), scope(user, tenant):
        invoice(tenant, net=net, vat=vat, gross=gross)


def test_due_date_cannot_precede_issue_date():
    user, tenant = world()
    with pytest.raises(IntegrityError), scope(user, tenant):
        invoice(tenant, issue_date=date(2026, 3, 10), due_date=date(2026, 3, 9))


def test_invoice_number_is_unique_within_a_firm_only():
    user, tenant = world()
    other_user, other = world()
    with scope(user, tenant):
        invoice(tenant, "F1")
    with scope(other_user, other):
        invoice(other, "F1")
    with pytest.raises(IntegrityError), scope(user, tenant):
        invoice(tenant, "F1")


def test_a_relation_to_another_firms_row_is_refused():
    user, tenant = world()
    other_user, other = world()
    with scope(other_user, other):
        foreign = customer(other)
    with pytest.raises(DatabaseError), scope(user, tenant):
        invoice(tenant, "F1", customer=foreign)
        connection.check_constraints()
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")


def test_a_payment_cannot_exceed_what_is_left():
    user, tenant = world()
    with scope(user, tenant):
        bill = invoice(tenant)
        sales_services.record_payment(bill.pk, date=date(2026, 3, 11), amount=D("100.00"))
        with pytest.raises(sales_services.SalesError):
            sales_services.record_payment(bill.pk, date=date(2026, 3, 12), amount=D("19.01"))
        sales_services.record_payment(bill.pk, date=date(2026, 3, 12), amount=D("19.00"))


def test_paid_total_is_not_multiplied_by_joins():
    user, tenant = world()
    with scope(user, tenant):
        bill = invoice(tenant)
        for amount in ("10.00", "20.00", "30.00"):
            sales_services.record_payment(bill.pk, date=date(2026, 3, 11), amount=D(amount))
        void = sales_services.record_payment(bill.pk, date=date(2026, 3, 11), amount=D("5.00"))
        sales_services.void_payment(void.pk, user_id=user.pk)
        assert sales_services.with_paid(Invoice.objects.all()).get(pk=bill.pk).paid == D("60.00")


def test_invoice_with_active_payments_cannot_be_cancelled():
    user, tenant = world()
    with scope(user, tenant):
        bill = invoice(tenant)
        payment = sales_services.record_payment(bill.pk, date=date(2026, 3, 11), amount=D("10.00"))
        with pytest.raises(sales_services.SalesError):
            sales_services.cancel_invoice(bill.pk, user_id=user.pk)
        sales_services.void_payment(payment.pk, user_id=user.pk)
        assert sales_services.cancel_invoice(bill.pk, user_id=user.pk).status == "cancelled"
        with pytest.raises(sales_services.SalesError):
            sales_services.record_payment(bill.pk, date=date(2026, 3, 12), amount=D("1.00"))


@pytest.mark.parametrize(
    "make,field",
    [
        (lambda t: invoice(t), "notes"),
        (lambda t: expense(t), "description"),
    ],
)
def test_financial_records_cannot_be_deleted_by_the_application(make, field):
    user, tenant = world()
    with pytest.raises(DatabaseError), scope(user, tenant):
        make(tenant).delete()


def test_stock_is_the_sum_of_movements_and_cannot_go_below_zero():
    user, tenant = world()
    with scope(user, tenant):
        item = product(tenant)
        on = date(2026, 3, 1)
        stock_services.record_movement(item.pk, date=on, kind="receipt", quantity=D("10"))
        stock_services.record_movement(item.pk, date=on, kind="issue", quantity=D("3.5"))
        stock_services.record_movement(item.pk, date=on, kind="adjustment", quantity=D("-1"))
        assert stock_services.level_of(item.pk) == D("5.500")
        with pytest.raises(stock_services.StockError):
            stock_services.record_movement(item.pk, date=on, kind="issue", quantity=D("5.501"))
        with pytest.raises(stock_services.StockError):
            stock_services.record_movement(item.pk, date=on, kind="receipt", quantity=D("-1"))


def test_stock_movements_are_append_only():
    user, tenant = world()
    with scope(user, tenant):
        item = product(tenant)
        move = stock_services.record_movement(
            item.pk, date=date(2026, 3, 1), kind="receipt", quantity=D("1")
        )
        with pytest.raises(DatabaseError), transaction.atomic():
            StockMovement.objects.filter(pk=move.pk).update(quantity=D("2"))
        with pytest.raises(DatabaseError), transaction.atomic():
            StockMovement.objects.filter(pk=move.pk).delete()


def test_database_refuses_a_movement_whose_sign_contradicts_its_kind():
    user, tenant = world()
    with pytest.raises(IntegrityError), scope(user, tenant):
        StockMovement.objects.create(
            tenant=tenant,
            product=product(tenant),
            date=date(2026, 3, 1),
            kind="issue",
            quantity=D("1"),
        )


def test_low_stock_uses_the_threshold_and_ignores_products_without_one():
    user, tenant = world()
    with scope(user, tenant):
        low = product(tenant, "A", reorder_threshold=D("5"))
        fine = product(tenant, "B", reorder_threshold=D("5"))
        product(tenant, "C")
        stock_services.record_movement(
            fine.pk, date=date(2026, 3, 1), kind="receipt", quantity=D("6")
        )
        assert [p.pk for p in stock_services.low_stock()] == [low.pk]


def test_recurring_generation_is_idempotent_and_respects_the_period():
    user, tenant = world()
    with scope(user, tenant):
        template = RecurringExpense.objects.create(
            tenant=tenant,
            description="Chirie",
            supplier="Proprietar",
            net=D("100.00"),
            vat=D("0.00"),
            gross=D("100.00"),
            day_of_month=15,
            first_month=date(2026, 3, 1),
            last_month=date(2026, 4, 1),
        )
        assert expense_services.generate_recurring(date(2026, 2, 1), user_id=user.pk) == 0
        assert expense_services.generate_recurring(date(2026, 3, 1), user_id=user.pk) == 1
        assert expense_services.generate_recurring(date(2026, 3, 1), user_id=user.pk) == 0
        assert expense_services.generate_recurring(date(2026, 5, 1), user_id=user.pk) == 0
        created = Expense.objects.get(recurring=template)
        assert created.date == date(2026, 3, 15)
        assert created.paid_date is None


def test_a_document_is_judged_by_its_content_and_stays_within_limits():
    user, tenant = world()
    with scope(user, tenant):
        record = expense(tenant)
        with pytest.raises(expense_services.DocumentRefused):
            expense_services.attach_document(
                record, name="x.pdf", content=b"<script>alert(1)</script>", user_id=user.pk
            )
        with pytest.raises(expense_services.DocumentRefused):
            expense_services.attach_document(
                record,
                name="x.pdf",
                content=b"%PDF-" + b"0" * expense_services.MAX_DOCUMENT_BYTES,
                user_id=user.pk,
            )
        first = expense_services.attach_document(
            record, name="a.pdf", content=b"%PDF-1.7 test", user_id=user.pk
        )
        again = expense_services.attach_document(
            record, name="b.pdf", content=b"%PDF-1.7 test", user_id=user.pk
        )
        assert first.pk == again.pk and first.content_type == "application/pdf"


def test_original_import_rows_cannot_be_rewritten():
    user, tenant = world()
    with scope(user, tenant):
        batch = ImportBatch.objects.create(
            tenant=tenant, kind="sales", original_name="a.csv", file_key="k", sha256="s", size=1
        )
        row = ImportRow.objects.create(
            tenant=tenant, batch=batch, number=2, raw={"a": 1}, status="valid"
        )
        with pytest.raises(DatabaseError), transaction.atomic():
            ImportRow.objects.filter(pk=row.pk).update(raw={"a": 2})
        with pytest.raises(DatabaseError), transaction.atomic():
            ImportRow.objects.filter(pk=row.pk).delete()
        ImportRow.objects.filter(pk=row.pk).update(status="invalid")
