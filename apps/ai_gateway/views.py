import uuid

from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.core.tasks import enqueue
from apps.tenants import roles

from .gateway import billing_period
from .models import AIBudget, AIBudgetAlert, AIBudgetPolicy, AIStoredResponse, AIUsageEvent
from .tasks import run_diagnostic


def _context(request):
    policy = AIBudgetPolicy.objects.first()
    budget = None
    if policy:
        start, _ = billing_period(timezone.now(), policy.billing_anchor_day)
        budget = AIBudget.objects.filter(period_start=start).first()
    used_percent = 0
    if budget and budget.limit_amount:
        used_percent = round(budget.spent / budget.limit_amount * 100, 1)
    return {
        "policy": policy,
        "budget": budget,
        "used_percent": used_percent,
        "alerts": AIBudgetAlert.objects.filter(budget=budget).order_by("threshold")
        if budget
        else [],
        "events": AIUsageEvent.objects.select_related("operation").order_by("-created_at")[:20],
        "last_response": AIStoredResponse.objects.order_by("-created_at").first(),
        "can_use": request.tenant_access.can(roles.USE_AI),
    }


@roles.requires(roles.VIEW_AI_USAGE)
def usage(request, tenant_id):
    is_partial = request.headers.get("HX-Request") == "true"
    template = "ai_gateway/_usage_body.html" if is_partial else "ai_gateway/usage.html"
    return render(request, template, _context(request))


@require_POST
@roles.requires(roles.USE_AI)
def run_test(request, tenant_id):
    enqueue(
        run_diagnostic,
        idempotency_key=str(uuid.uuid4()),
        note="Test din pagina de consum AI.",
    )
    messages.success(request, "Testul a fost pus în coadă. Rezultatul apare mai jos.")
    return redirect("tenant:ai-usage", tenant_id=tenant_id)
