from datetime import timedelta

from django.utils import timezone

from apps.tenants import roles

from . import figures


def month_from_request(request, today):
    text = request.GET.get("luna", "")
    try:
        year, month = (int(part) for part in text.split("-"))
        chosen = today.replace(year=year, month=month, day=1)
    except ValueError:
        return today.replace(day=1)
    return chosen if 2000 <= chosen.year <= today.year + 1 else today.replace(day=1)


def dashboard_context(request):
    if not request.tenant_access.can(roles.VIEW_FINANCE):
        return {"show_finance": False}
    today = timezone.localdate()
    month = month_from_request(request, today)
    month_end = figures.add_months(month, 1) - timedelta(days=1)
    as_of = min(month_end, today)
    period = figures.period_figures(month, month_end)
    series = figures.monthly_series(month)
    return {
        "show_finance": True,
        "month": month,
        "month_value": month.strftime("%Y-%m"),
        "month_label": figures.month_label(month),
        "as_of": as_of,
        "period": period,
        "outstanding": figures.outstanding(as_of),
        "cash": figures.cash_position(as_of),
        "alerts": figures.alerts(today),
        "series": series,
        "chart": figures.chart_payload(series),
        "has_series": any(row["revenue_net"] or row["expenses_net"] for row in series),
        "vat_confirmed": figures.vat_status_is_confirmed_payer(),
    }
