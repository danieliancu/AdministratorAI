"""Every figure shown to a firm, calculated in one place from the records it entered.

Nothing here is an accounting result. Issuing, collecting, recording and estimating stay
separate, and each figure is labelled for what it is by the pages that show it.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Count, Sum
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.expenses.models import Expense
from apps.expenses.services import missing_recurring
from apps.financial_imports.models import ImportBatch
from apps.inventory.models import Product
from apps.inventory.services import low_stock, movements_between, with_stock
from apps.sales.models import Invoice, Payment, SaleTransaction
from apps.sales.services import with_paid
from apps.tenants.models import CompanyFiscalProfile

from .models import OpeningCash

ZERO = Decimal("0.00")
MONTH_NAMES = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "noi", "dec"]
AGING_BUCKETS = (
    ("not_due", "Nescadente"),
    ("d1_30", "1–30 zile"),
    ("d31_60", "31–60 zile"),
    ("d61_90", "61–90 zile"),
    ("d90_plus", "Peste 90 de zile"),
)


def _sum(queryset, field):
    return queryset.aggregate(total=Sum(field))["total"] or ZERO


def _issued():
    return Invoice.objects.filter(status=Invoice.Status.ISSUED)


def _payments():
    return Payment.objects.filter(voided_at__isnull=True)


def _direct_sales():
    return SaleTransaction.objects.filter(voided_at__isnull=True)


def _expenses():
    return Expense.objects.filter(voided_at__isnull=True)


@dataclass(frozen=True)
class PeriodFigures:
    start: date
    end: date
    invoice_count: int
    invoiced_net: Decimal
    invoiced_vat: Decimal
    invoiced_gross: Decimal
    direct_count: int
    direct_net: Decimal
    direct_gross: Decimal
    received_on_invoices: Decimal
    expense_count: int
    expenses_net: Decimal
    expenses_vat: Decimal
    expenses_gross: Decimal
    expenses_paid: Decimal

    @property
    def revenue_net(self):
        return self.invoiced_net + self.direct_net

    @property
    def received_total(self):
        return self.received_on_invoices + self.direct_gross

    @property
    def net_cash_flow(self):
        return self.received_total - self.expenses_paid

    @property
    def estimated_result(self):
        return self.revenue_net - self.expenses_net

    @property
    def has_records(self):
        return bool(self.invoice_count or self.direct_count or self.expense_count)


def period_figures(start, end):
    invoices = _issued().filter(issue_date__range=(start, end))
    invoice_totals = invoices.aggregate(
        n=Count("pk"), net=Sum("net"), vat=Sum("vat"), gross=Sum("gross")
    )
    direct = _direct_sales().filter(date__range=(start, end))
    direct_totals = direct.aggregate(n=Count("pk"), net=Sum("net"), gross=Sum("gross"))
    expenses = _expenses().filter(date__range=(start, end))
    expense_totals = expenses.aggregate(
        n=Count("pk"), net=Sum("net"), vat=Sum("vat"), gross=Sum("gross")
    )
    return PeriodFigures(
        start=start,
        end=end,
        invoice_count=invoice_totals["n"],
        invoiced_net=invoice_totals["net"] or ZERO,
        invoiced_vat=invoice_totals["vat"] or ZERO,
        invoiced_gross=invoice_totals["gross"] or ZERO,
        direct_count=direct_totals["n"],
        direct_net=direct_totals["net"] or ZERO,
        direct_gross=direct_totals["gross"] or ZERO,
        received_on_invoices=_sum(_payments().filter(date__range=(start, end)), "amount"),
        expense_count=expense_totals["n"],
        expenses_net=expense_totals["net"] or ZERO,
        expenses_vat=expense_totals["vat"] or ZERO,
        expenses_gross=expense_totals["gross"] or ZERO,
        expenses_paid=_sum(_expenses().filter(paid_date__range=(start, end)), "gross"),
    )


def outstanding(as_of):
    """Invoiced but not collected by a date. Payments made later do not count yet."""
    issued = _sum(_issued().filter(issue_date__lte=as_of), "gross")
    collected = _sum(
        _payments().filter(
            date__lte=as_of,
            invoice__status=Invoice.Status.ISSUED,
            invoice__issue_date__lte=as_of,
        ),
        "amount",
    )
    return issued - collected


def unpaid_invoices(as_of):
    rows = []
    invoices = with_paid(
        _issued().filter(issue_date__lte=as_of).select_related("customer"), as_of=as_of
    ).order_by("due_date", "issue_date")
    for invoice in invoices:
        remaining = invoice.gross - invoice.paid
        if remaining > 0:
            invoice.remaining = remaining
            invoice.days_overdue = (
                (as_of - invoice.due_date).days
                if invoice.due_date and invoice.due_date < as_of
                else 0
            )
            rows.append(invoice)
    return rows


def _bucket_of(days_overdue):
    if days_overdue <= 0:
        return "not_due"
    if days_overdue <= 30:
        return "d1_30"
    if days_overdue <= 60:
        return "d31_60"
    if days_overdue <= 90:
        return "d61_90"
    return "d90_plus"


def aging(as_of):
    totals = {key: ZERO for key, _label in AGING_BUCKETS}
    counts = {key: 0 for key, _label in AGING_BUCKETS}
    invoices = unpaid_invoices(as_of)
    for invoice in invoices:
        bucket = _bucket_of(invoice.days_overdue)
        totals[bucket] += invoice.remaining
        counts[bucket] += 1
    return {
        "invoices": invoices,
        "buckets": [
            {"label": label, "total": totals[key], "count": counts[key]}
            for key, label in AGING_BUCKETS
        ],
        "total": sum(totals.values(), ZERO),
    }


@dataclass(frozen=True)
class CashPosition:
    opening: Decimal
    opening_date: date
    as_of: date
    received: Decimal
    paid: Decimal

    @property
    def amount(self):
        return self.opening + self.received - self.paid


def cash_position(as_of):
    """Declared balance plus recorded money movements. Unknown without a declared balance."""
    declared = OpeningCash.objects.first()
    if declared is None or as_of < declared.as_of:
        return None
    window = {"date__gt": declared.as_of, "date__lte": as_of}
    received = _sum(_payments().filter(**window), "amount") + _sum(
        _direct_sales().filter(**window), "gross"
    )
    paid = _sum(_expenses().filter(paid_date__gt=declared.as_of, paid_date__lte=as_of), "gross")
    return CashPosition(declared.amount, declared.as_of, as_of, received, paid)


def first_of_month(day):
    return day.replace(day=1)


def add_months(month, count):
    index = month.year * 12 + month.month - 1 + count
    return date(index // 12, index % 12 + 1, 1)


def month_label(month):
    return f"{MONTH_NAMES[month.month - 1]} {month.year}"


def _by_month(queryset, date_field, value_field):
    rows = (
        queryset.annotate(month=TruncMonth(date_field))
        .order_by()
        .values("month")
        .annotate(total=Sum(value_field))
    )
    return {row["month"]: row["total"] for row in rows}


def monthly_series(last_month, count=12):
    first = add_months(last_month, -(count - 1))
    end = add_months(last_month, 1) - timedelta(days=1)
    invoiced = _by_month(_issued().filter(issue_date__range=(first, end)), "issue_date", "net")
    direct = _direct_sales().filter(date__range=(first, end))
    direct_net = _by_month(direct, "date", "net")
    direct_gross = _by_month(direct, "date", "gross")
    expenses = _by_month(_expenses().filter(date__range=(first, end)), "date", "net")
    collected = _by_month(_payments().filter(date__range=(first, end)), "date", "amount")
    series = []
    for offset in range(count):
        month = add_months(first, offset)
        series.append(
            {
                "month": month,
                "label": month_label(month),
                "revenue_net": invoiced.get(month, ZERO) + direct_net.get(month, ZERO),
                "expenses_net": expenses.get(month, ZERO),
                "received": collected.get(month, ZERO) + direct_gross.get(month, ZERO),
            }
        )
    return series


def chart_payload(series):
    return {
        "labels": [row["label"] for row in series],
        "datasets": [
            {
                "label": "Venituri înregistrate (fără TVA)",
                "data": [float(row["revenue_net"]) for row in series],
            },
            {
                "label": "Cheltuieli înregistrate (fără TVA)",
                "data": [float(row["expenses_net"]) for row in series],
            },
        ],
    }


def previous_period(start, end):
    """The previous calendar month for a whole month, otherwise the same number of days."""
    is_whole_month = start.day == 1 and end == add_months(start, 1) - timedelta(days=1)
    if is_whole_month:
        previous = add_months(start, -1)
        return previous, start - timedelta(days=1)
    length = end - start
    previous_end = start - timedelta(days=1)
    return previous_end - length, previous_end


def change(current, previous):
    """Absolute change, plus a percentage only when the comparison base is positive."""
    difference = current - previous
    percent = None
    if previous > 0:
        percent = (difference * 100 / previous).quantize(Decimal("0.1"))
    return {"current": current, "previous": previous, "difference": difference, "percent": percent}


def sales_by_category(start, end):
    totals = {}
    for queryset in (
        _issued().filter(issue_date__range=(start, end)),
        _direct_sales().filter(date__range=(start, end)),
    ):
        for row in queryset.order_by().values("category__name").annotate(total=Sum("net")):
            name = row["category__name"] or "Fără categorie"
            totals[name] = totals.get(name, ZERO) + row["total"]
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)


def expenses_by_category(start, end):
    rows = (
        _expenses()
        .filter(date__range=(start, end))
        .order_by()
        .values("category__name")
        .annotate(total=Sum("net"), n=Count("pk"))
        .order_by("-total")
    )
    return [(row["category__name"] or "Fără categorie", row["total"]) for row in rows]


def top_customers(start, end, limit=10):
    return list(
        _issued()
        .filter(issue_date__range=(start, end))
        .order_by()
        .values("customer__name")
        .annotate(net=Sum("net"), gross=Sum("gross"), n=Count("pk"))
        .order_by("-net")[:limit]
    )


def top_suppliers(start, end, limit=10):
    return list(
        _expenses()
        .filter(date__range=(start, end))
        .order_by()
        .values("supplier")
        .annotate(net=Sum("net"), gross=Sum("gross"), n=Count("pk"))
        .order_by("-net")[:limit]
    )


def inventory_report(start, end):
    moved = {row["product_id"]: row for row in movements_between(start, end)}
    products = list(with_stock(Product.objects.filter(is_active=True)).order_by("name"))
    value = ZERO
    without_cost = 0
    rows = []
    for product in products:
        row = moved.get(product.pk, {})
        worth = None
        if product.unit_cost is None:
            without_cost += 1 if product.stock else 0
        else:
            worth = (product.stock * product.unit_cost).quantize(Decimal("0.01"))
            value += worth
        rows.append(
            {
                "product": product,
                "received": row.get("received", Decimal(0)),
                "issued": row.get("issued", Decimal(0)),
                "adjusted": row.get("adjusted", Decimal(0)),
                "value": worth,
                "is_low": (
                    product.reorder_threshold is not None
                    and product.stock <= product.reorder_threshold
                ),
            }
        )
    return {"rows": rows, "value": value, "without_cost": without_cost}


def _months_in(start, end):
    months = []
    month = first_of_month(start)
    while month <= end:
        months.append(month)
        month = add_months(month, 1)
    return months


def empty_months(start, end):
    """Whole months with no sales or no expenses, which usually means missing records."""
    sales = {
        row["month"]
        for row in _issued()
        .filter(issue_date__range=(start, end))
        .annotate(month=TruncMonth("issue_date"))
        .order_by()
        .values("month")
    } | {
        row["month"]
        for row in _direct_sales()
        .filter(date__range=(start, end))
        .annotate(month=TruncMonth("date"))
        .order_by()
        .values("month")
    }
    expenses = {
        row["month"]
        for row in _expenses()
        .filter(date__range=(start, end))
        .annotate(month=TruncMonth("date"))
        .order_by()
        .values("month")
    }
    months = _months_in(start, end)
    return {
        "sales": [month_label(m) for m in months if m not in sales],
        "expenses": [month_label(m) for m in months if m not in expenses],
    }


def alerts(today=None):
    today = today or timezone.localdate()
    found = []
    overdue = [i for i in unpaid_invoices(today) if i.days_overdue > 0]
    if overdue:
        amount = sum((i.remaining for i in overdue), ZERO)
        found.append(
            {
                "kind": "overdue",
                "route": "report-receivables",
                "count": len(overdue),
                "amount": amount,
            }
        )
    low = low_stock().count()
    if low:
        found.append({"kind": "low_stock", "route": "product-list", "count": low})
    due = missing_recurring(first_of_month(today)).count()
    if due:
        found.append({"kind": "recurring", "route": "recurring-list", "count": due})
    pending = ImportBatch.objects.filter(status=ImportBatch.Status.PREVIEW).count()
    if pending:
        found.append({"kind": "imports", "route": "import-list", "count": pending})
    if not OpeningCash.objects.exists():
        found.append({"kind": "opening_cash", "route": "opening-cash"})
    return found


def vat_status_is_confirmed_payer():
    profile = CompanyFiscalProfile.objects.first()
    return profile is not None and profile.vat_status == CompanyFiscalProfile.VatStatus.PAYER
