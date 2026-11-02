from datetime import timedelta

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone

from apps.audit.services import record_tenant_event
from apps.core.exports import csv_response
from apps.core.numbers import BadValue, parse_date
from apps.tenants import roles
from apps.tenants.roles import requires

from . import figures
from .forms import OpeningCashForm
from .models import OpeningCash

MAX_PERIOD_DAYS = 3660


def period_from_request(request):
    """Falls back to the current month when the dates are missing or make no sense."""
    today = timezone.localdate()
    default = (
        today.replace(day=1),
        figures.add_months(today.replace(day=1), 1) - timedelta(days=1),
    )
    try:
        start = parse_date(request.GET["de_la"])
        end = parse_date(request.GET["pana_la"])
    except (KeyError, BadValue):
        return default
    if start > end or (end - start).days > MAX_PERIOD_DAYS:
        return default
    return start, end


def _wants_csv(request):
    return request.GET.get("export") == "csv"


def _base(request, active, start, end):
    return {
        "start": start,
        "end": end,
        "active_report": active,
        "active_section": "report-summary",
        "empty": figures.empty_months(start, end),
    }


def _comparison(current, previous):
    return [
        (
            "Venituri înregistrate, fără TVA",
            figures.change(current.revenue_net, previous.revenue_net),
        ),
        ("Facturat, cu TVA", figures.change(current.invoiced_gross, previous.invoiced_gross)),
        ("Încasat", figures.change(current.received_total, previous.received_total)),
        (
            "Cheltuieli înregistrate, fără TVA",
            figures.change(current.expenses_net, previous.expenses_net),
        ),
        ("Cheltuieli plătite", figures.change(current.expenses_paid, previous.expenses_paid)),
        (
            "Rezultat estimat înainte de impozite",
            figures.change(current.estimated_result, previous.estimated_result),
        ),
    ]


@requires(roles.VIEW_FINANCE)
def report_summary(request, tenant_id):
    start, end = period_from_request(request)
    current = figures.period_figures(start, end)
    previous_start, previous_end = figures.previous_period(start, end)
    rows = _comparison(current, figures.period_figures(previous_start, previous_end))
    if _wants_csv(request):
        return csv_response(
            f"sumar-{start}-{end}.csv",
            ["Indicator", "Perioada", "Perioada anterioară", "Diferență"],
            ((label, c["current"], c["previous"], c["difference"]) for label, c in rows),
        )
    return render(
        request,
        "reports/summary.html",
        {
            **_base(request, "summary", start, end),
            "figures": current,
            "rows": rows,
            "previous_start": previous_start,
            "previous_end": previous_end,
            "outstanding": figures.outstanding(end),
            "cash": figures.cash_position(end),
            "vat_confirmed": figures.vat_status_is_confirmed_payer(),
        },
    )


@requires(roles.VIEW_FINANCE)
def report_sales(request, tenant_id):
    start, end = period_from_request(request)
    categories = figures.sales_by_category(start, end)
    customers = figures.top_customers(start, end)
    if _wants_csv(request):
        return csv_response(
            f"vanzari-{start}-{end}.csv",
            ["Tip", "Denumire", "Valoare fără TVA"],
            [
                *(("Categorie", name, total) for name, total in categories),
                *(("Client", row["customer__name"], row["net"]) for row in customers),
            ],
        )
    series = figures.monthly_series(figures.first_of_month(end))
    return render(
        request,
        "reports/sales.html",
        {
            **_base(request, "sales", start, end),
            "categories": categories,
            "customers": customers,
            "series": series,
        },
    )


@requires(roles.VIEW_FINANCE)
def report_expenses(request, tenant_id):
    start, end = period_from_request(request)
    categories = figures.expenses_by_category(start, end)
    suppliers = figures.top_suppliers(start, end)
    if _wants_csv(request):
        return csv_response(
            f"cheltuieli-{start}-{end}.csv",
            ["Tip", "Denumire", "Valoare fără TVA"],
            [
                *(("Categorie", name, total) for name, total in categories),
                *(("Furnizor", row["supplier"], row["net"]) for row in suppliers),
            ],
        )
    return render(
        request,
        "reports/expenses.html",
        {
            **_base(request, "expenses", start, end),
            "categories": categories,
            "suppliers": suppliers,
            "series": figures.monthly_series(figures.first_of_month(end)),
        },
    )


@requires(roles.VIEW_FINANCE)
def report_receivables(request, tenant_id):
    as_of = timezone.localdate()
    report = figures.aging(as_of)
    if _wants_csv(request):
        return csv_response(
            f"creante-{as_of}.csv",
            ["Factură", "Client", "Scadență", "Total", "Încasat", "Rest", "Zile întârziere"],
            (
                (
                    i.number,
                    i.customer.name,
                    i.due_date,
                    i.gross,
                    i.paid,
                    i.remaining,
                    i.days_overdue,
                )
                for i in report["invoices"]
            ),
        )
    return render(
        request,
        "reports/receivables.html",
        {
            "report": report,
            "as_of": as_of,
            "active_report": "receivables",
            "active_section": "report-summary",
        },
    )


@requires(roles.VIEW_FINANCE)
def report_inventory(request, tenant_id):
    start, end = period_from_request(request)
    report = figures.inventory_report(start, end)
    if _wants_csv(request):
        return csv_response(
            f"stocuri-{start}-{end}.csv",
            ["Cod", "Produs", "UM", "Stoc", "Intrări", "Ieșiri", "Ajustări", "Valoare estimată"],
            (
                (
                    r["product"].sku,
                    r["product"].name,
                    r["product"].unit,
                    r["product"].stock,
                    r["received"],
                    r["issued"],
                    r["adjusted"],
                    r["value"],
                )
                for r in report["rows"]
            ),
        )
    return render(
        request,
        "reports/inventory.html",
        {
            "report": report,
            "start": start,
            "end": end,
            "active_report": "inventory",
            "active_section": "report-summary",
        },
    )


@requires(roles.EDIT_FINANCE)
def opening_cash(request, tenant_id):
    existing = OpeningCash.objects.first()
    form = OpeningCashForm(request.POST or None, instance=existing, tenant_id=tenant_id)
    if request.method == "POST" and form.is_valid():
        declared = form.save(commit=False)
        declared.declared_by_id = request.user.pk
        declared.updated_at = timezone.now()
        declared.save()
        record_tenant_event(
            "cash.opening_declared",
            actor_user_id=request.user.pk,
            metadata={"changes": form.changes()},
        )
        messages.success(request, "Soldul a fost salvat.")
        return redirect("tenant:dashboard", tenant_id=tenant_id)
    return render(
        request,
        "components/form_page.html",
        {
            "form": form,
            "title": "Sold inițial de numerar",
            "submit": "Salvează soldul",
            "note": "Declarat de tine, neverificat. Pe baza lui estimăm poziția de numerar, "
            "adunând încasările și scăzând plățile înregistrate după această dată.",
            "active_section": "dashboard",
        },
    )
