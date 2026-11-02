"""Real transactions and real threads: a test transaction would hide every race here."""

import threading
from datetime import date
from decimal import Decimal as D

from django.db import connections

from apps.core.db.scope import db_scope
from apps.expenses.models import Expense
from apps.financial_imports.services import commit_batch, create_batch
from apps.inventory import services as stock_services
from apps.sales import services as sales_services
from apps.sales.models import Payment
from tests.finance.helpers import invoice, product, scope, world

CSV = (
    b"data;furnizor;numar_document;net;tva;total\n"
    b"10.03.2026;A;1;1;0;1\n"
    b"10.03.2026;B;2;1;0;1\n"
)


def _parallel(jobs):
    errors, results, barrier = [], [], threading.Barrier(len(jobs), timeout=20)

    def run(job):
        try:
            barrier.wait()
            results.append(job())
        except Exception as exc:
            errors.append(exc)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=run, args=[job]) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    return results, errors


def test_concurrent_payments_cannot_overpay(committed_db):
    user, tenant = world()
    with scope(user, tenant):
        bill = invoice(tenant)

    def pay():
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            return sales_services.record_payment(
                bill.pk, date=date(2026, 3, 11), amount=D("100.00")
            )

    results, errors = _parallel([pay, pay])
    assert len(results) == 1
    assert [type(e) for e in errors] == [sales_services.SalesError]
    with scope(user, tenant):
        assert Payment.objects.filter(invoice_id=bill.pk).count() == 1


def test_concurrent_issues_cannot_take_stock_below_zero(committed_db):
    user, tenant = world()
    with scope(user, tenant):
        item = product(tenant)
        stock_services.record_movement(
            item.pk, date=date(2026, 3, 1), kind="receipt", quantity=D("1")
        )

    def issue():
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            return stock_services.record_movement(
                item.pk, date=date(2026, 3, 2), kind="issue", quantity=D("1")
            )

    results, errors = _parallel([issue, issue])
    assert len(results) == 1
    assert [type(e) for e in errors] == [stock_services.StockError]


def test_concurrent_commits_import_once(committed_db):
    user, tenant = world()
    with scope(user, tenant):
        batch, _ = create_batch("expenses", "a.csv", CSV, user_id=user.pk)

    def commit():
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            return commit_batch(batch.pk, user_id=user.pk)

    results, errors = _parallel([commit, commit])
    assert errors == [] and len(results) == 2
    with scope(user, tenant):
        assert Expense.objects.count() == 2


def test_concurrent_uploads_of_one_file_make_one_batch(committed_db):
    user, tenant = world()

    def upload():
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            return create_batch("expenses", "a.csv", CSV, user_id=user.pk)[0].pk

    results, errors = _parallel([upload, upload])
    assert errors == [] and len(set(results)) == 1
