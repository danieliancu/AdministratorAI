from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import ai_services, services
from .access import MANAGE, VIEW, requires_platform
from .forms import AIPolicyForm, ReconciliationForm, TenantCreateForm, TenantStatusForm

PAGE_SIZE = 25
POLICY_FIELDS = (
    "monthly_limit",
    "overage_authorised",
    "overage_limit",
    "max_cost_per_request",
    "max_output_tokens",
    "user_daily_limit",
    "user_monthly_limit",
    "requests_per_minute",
    "billing_anchor_day",
    "allowed_models",
    "allowed_operations",
)


def _page(request, rows):
    return Paginator(rows, PAGE_SIZE).get_page(request.GET.get("pagina"))


@requires_platform(VIEW)
def overview(request):
    return render(request, "platform/overview.html", {"counts": services.counts()})


@requires_platform(VIEW)
def tenant_list(request):
    search = request.GET.get("q", "").strip()
    is_partial = request.headers.get("HX-Request") == "true"
    return render(
        request,
        "platform/_tenants_table.html" if is_partial else "platform/tenants.html",
        {
            "page": _page(request, services.tenants(search)),
            "search": search,
            "can_manage": request.platform_access.can(MANAGE),
        },
    )


@requires_platform(MANAGE)
def tenant_new(request):
    form = TenantCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.create_tenant(
                request.user.pk,
                name=form.cleaned_data["name"],
                owner_login=form.cleaned_data["owner_login"],
                reason=form.cleaned_data["reason"],
            )
        except DatabaseError:
            form.add_error("owner_login", "Nu există un cont cu această adresă.")
        else:
            messages.success(request, "Firma a fost creată.")
            return redirect("platform:tenants")
    return render(request, "platform/tenant_new.html", {"form": form})


@require_POST
@requires_platform(MANAGE)
def tenant_status(request, tenant_id):
    form = TenantStatusForm(request.POST)
    if form.is_valid():
        services.set_tenant_status(
            request.user.pk, tenant_id, form.cleaned_data["status"], form.cleaned_data["reason"]
        )
        messages.success(request, "Starea firmei a fost schimbată.")
    else:
        messages.error(request, "Motivul este obligatoriu.")
    return redirect("platform:tenants")


@requires_platform(VIEW)
def user_list(request):
    return render(request, "platform/users.html", {"page": _page(request, services.users())})


@requires_platform(VIEW)
def audit_log(request):
    return render(request, "platform/audit.html", {"page": _page(request, services.audit_log())})


@requires_platform(VIEW)
def ai_usage(request):
    return render(
        request,
        "platform/ai_usage.html",
        {
            "usage": ai_services.tenant_usage(),
            "tenants": services.tenants(),
            "uncertain": ai_services.uncertain_reservations(),
            "can_manage": request.platform_access.can(MANAGE),
        },
    )


@requires_platform(VIEW)
def ai_costs(request):
    return render(
        request,
        "platform/ai_costs.html",
        {
            "breakdown": ai_services.cost_breakdown(),
            "reconciliations": ai_services.reconciliations(),
            "form": ReconciliationForm(),
            "can_manage": request.platform_access.can(MANAGE),
        },
    )


@requires_platform(MANAGE)
def ai_policy(request, tenant_id):
    current = ai_services.tenant_usage_one(tenant_id)
    initial = {name: current[name] for name in POLICY_FIELDS} if current else {}
    form = AIPolicyForm(request.POST or None, catalog=ai_services.catalog(), initial=initial)
    if request.method == "POST" and form.is_valid():
        data = dict(form.cleaned_data)
        reason = data.pop("reason")
        ai_services.set_policy(request.user.pk, tenant_id, reason=reason, **data)
        messages.success(request, "Politica AI a fost salvată.")
        return redirect("platform:ai-usage")
    return render(request, "platform/ai_policy.html", {"form": form, "current": current})


@require_POST
@requires_platform(MANAGE)
def ai_resolve(request, reservation_id):
    reason = request.POST.get("reason", "").strip()
    raw = request.POST.get("actual", "").strip()
    try:
        actual = Decimal(raw) if raw else None
        ai_services.resolve_reservation(request.user.pk, reservation_id, actual, reason)
    except (InvalidOperation, DatabaseError):
        messages.error(request, "Rezervarea nu a putut fi rezolvată. Verifică suma și motivul.")
    else:
        messages.success(request, "Rezervarea a fost rezolvată.")
    return redirect("platform:ai-usage")


@require_POST
@requires_platform(MANAGE)
def ai_reconcile(request):
    form = ReconciliationForm(request.POST)
    if not form.is_valid():
        messages.error(request, "Completează corect toate câmpurile.")
        return redirect("platform:ai-costs")
    try:
        ai_services.record_reconciliation(request.user.pk, **form.cleaned_data)
    except DatabaseError:
        messages.error(request, "Reconcilierea nu a putut fi salvată. Verifică providerul.")
    else:
        messages.success(request, "Reconcilierea a fost salvată.")
    return redirect("platform:ai-costs")
