"""Hand-calculated figures. Each value here was worked out on paper from the rows above it."""

from datetime import date
from decimal import Decimal as D

import pytest

from apps.expenses.models import RecurringExpense
from apps.inventory.services import record_movement
from apps.reports import figures
from apps.reports.models import OpeningCash
from apps.sales.services import cancel_invoice, record_payment, void_payment, void_sale
from tests.finance.helpers import expense, invoice, product, sale, scope, world

pytestmark = pytest.mark.django_db
MARCH = (date(2026, 3, 1), date(2026, 3, 31))


@pytest.fixture
def books():
    user, tenant = world()
    with scope(user, tenant):
        # Issued in March, half collected in March and the rest in April.
        first = invoice(tenant, "F1", due_date=date(2026, 3, 20))
        record_payment(first.pk, date=date(2026, 3, 15), amount=D("60.00"))
        record_payment(first.pk, date=date(2026, 4, 2), amount=D("59.00"))
        # Issued in March, nothing collected.
        invoice(tenant, "F2", net="200.00", vat="38.00", gross="238.00")
        # Cancelled: counts nowhere.
        cancel_invoice(
            invoice(tenant, "F3", net="900.00", vat="0.00", gross="900.00").pk, user_id=user.pk
        )
        # A voided payment on an April invoice counts nowhere.
        fourth = invoice(tenant, "F4", issue_date=date(2026, 4, 1))
        void_payment(
            record_payment(fourth.pk, date=date(2026, 3, 31), amount=D("5.00")).pk, user_id=user.pk
        )
        sale(tenant)
        void_sale(sale(tenant, net="10.00", vat="0.00", gross="10.00").pk, user_id=user.pk)
        expense(tenant, paid_date=date(2026, 4, 5))
        expense(tenant, net="10.00", vat="0.00", gross="10.00", paid_date=date(2026, 3, 13))
        expense(tenant, net="70.00", vat="0.00", gross="70.00", voided_at="2026-03-20T10:00:00Z")
    return user, tenant


def test_period_keeps_issued_collected_and_recorded_apart(books):
    with scope(*books):
        p = figures.period_figures(*MARCH)
    assert (p.invoice_count, p.invoiced_net, p.invoiced_vat, p.invoiced_gross) == (
        2,
        D("300.00"),
        D("57.00"),
        D("357.00"),
    )
    assert (p.direct_count, p.direct_net, p.direct_gross) == (1, D("50.00"), D("59.50"))
    assert p.revenue_net == D("350.00")
    assert p.received_on_invoices == D("60.00")
    assert p.received_total == D("119.50")
    assert (p.expense_count, p.expenses_net, p.expenses_vat, p.expenses_gross) == (
        2,
        D("50.00"),
        D("7.60"),
        D("57.60"),
    )
    assert p.expenses_paid == D("10.00")
    assert p.net_cash_flow == D("109.50")
    assert p.estimated_result == D("300.00")


def test_outstanding_depends_on_the_date(books):
    with scope(*books):
        assert figures.outstanding(date(2026, 3, 14)) == D("357.00")
        assert figures.outstanding(date(2026, 3, 31)) == D("297.00")
        # F1 is settled; F2 stays open, and F4 was issued on 1 April.
        assert figures.outstanding(date(2026, 4, 30)) == D("357.00")


def test_aging_buckets_add_up_to_outstanding(books):
    with scope(*books):
        report = figures.aging(date(2026, 3, 31))
        assert report["total"] == figures.outstanding(date(2026, 3, 31))
    by_label = {b["label"]: b for b in report["buckets"]}
    assert by_label["Nescadente"]["total"] == D("238.00")
    assert by_label["1–30 zile"]["total"] == D("59.00")
    assert [i.number for i in report["invoices"]] == ["F1", "F2"]


def test_no_cash_position_without_a_declared_balance(books):
    with scope(*books):
        assert figures.cash_position(date(2026, 3, 31)) is None


def test_cash_position_counts_only_movements_after_the_declared_day(books):
    user, tenant = books
    with scope(user, tenant):
        OpeningCash.objects.create(tenant=tenant, amount=D("1000.00"), as_of=date(2026, 3, 13))
        cash = figures.cash_position(date(2026, 3, 31))
        # +60 payment on 15 March; the sale of 11 March and payment of 13 March came before.
        assert (cash.received, cash.paid, cash.amount) == (D("60.00"), D("0.00"), D("1060.00"))
        later = figures.cash_position(date(2026, 4, 30))
        assert (later.received, later.paid) == (D("119.00"), D("47.60"))
        assert later.amount == D("1071.40")
        assert figures.cash_position(date(2026, 3, 12)) is None


def test_monthly_series_covers_empty_months_with_zero(books):
    with scope(*books):
        series = figures.monthly_series(date(2026, 4, 1), count=3)
    assert [r["label"] for r in series] == ["feb 2026", "mar 2026", "apr 2026"]
    assert series[0]["revenue_net"] == D("0.00")
    assert series[1]["revenue_net"] == D("350.00")
    assert series[1]["expenses_net"] == D("50.00")
    assert series[1]["received"] == D("119.50")
    assert series[2]["revenue_net"] == D("100.00")
    assert series[2]["received"] == D("59.00")


def test_series_crosses_the_year_boundary():
    assert figures.add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
    assert figures.add_months(date(2025, 12, 1), 1) == date(2026, 1, 1)


def test_previous_period():
    assert figures.previous_period(*MARCH) == (date(2026, 2, 1), date(2026, 2, 28))
    assert figures.previous_period(date(2026, 3, 10), date(2026, 3, 19)) == (
        date(2026, 2, 28),
        date(2026, 3, 9),
    )


def test_change_gives_no_percentage_without_a_positive_base():
    assert figures.change(D("150"), D("100"))["percent"] == D("50.0")
    assert figures.change(D("150"), D("0"))["percent"] is None
    assert figures.change(D("150"), D("-10"))["percent"] is None


def test_breakdowns(books):
    with scope(*books):
        assert figures.sales_by_category(*MARCH) == [("Fără categorie", D("350.00"))]
        assert figures.expenses_by_category(*MARCH) == [("Fără categorie", D("50.00"))]
        customers = figures.top_customers(*MARCH)
        assert [c["customer__name"] for c in customers] == ["Client F2", "Client F1"]
        assert figures.top_suppliers(*MARCH)[0]["net"] == D("50.00")


def test_inventory_value_excludes_products_without_a_cost():
    user, tenant = world()
    on = date(2026, 3, 2)
    with scope(user, tenant):
        costed = product(tenant, "A", unit_cost=D("2.50"), reorder_threshold=D("5"))
        uncosted = product(tenant, "B")
        record_movement(costed.pk, date=on, kind="receipt", quantity=D("4"))
        record_movement(uncosted.pk, date=on, kind="receipt", quantity=D("1"))
        record_movement(costed.pk, date=date(2026, 5, 1), kind="issue", quantity=D("1"))
        report = figures.inventory_report(*MARCH)
    assert report["value"] == D("7.50")
    assert report["without_cost"] == 1
    first = report["rows"][0]
    assert first["received"] == D("4.000") and first["issued"] == D(0) and first["is_low"]


def test_alerts_name_only_what_exists():
    user, tenant = world()
    today = date(2026, 3, 25)
    with scope(user, tenant):
        assert [a["kind"] for a in figures.alerts(today)] == ["opening_cash"]
        OpeningCash.objects.create(tenant=tenant, amount=D("0.00"), as_of=date(2026, 3, 1))
        assert figures.alerts(today) == []
        invoice(tenant, "F1", due_date=date(2026, 3, 20))
        product(tenant, "A", reorder_threshold=D("1"))
        RecurringExpense.objects.create(
            tenant=tenant,
            description="Chirie",
            supplier="P",
            net=D("1.00"),
            vat=D("0.00"),
            gross=D("1.00"),
            first_month=date(2026, 1, 1),
        )
        found = {a["kind"]: a for a in figures.alerts(today)}
    assert set(found) == {"overdue", "low_stock", "recurring"}
    assert found["overdue"]["amount"] == D("119.00")


def test_empty_months_are_reported():
    user, tenant = world()
    with scope(user, tenant):
        invoice(tenant, "F1")
        empty = figures.empty_months(date(2026, 2, 1), date(2026, 3, 31))
    assert empty == {"sales": ["feb 2026"], "expenses": ["feb 2026", "mar 2026"]}
