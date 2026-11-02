from datetime import timedelta

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.ai_gateway.models import AIBudgetPolicy
from apps.audit.services import record_tenant_event
from apps.core.listing import is_htmx, page_of
from apps.core.tasks import enqueue
from apps.tenants import roles
from apps.tenants.roles import requires

from .answering import OPERATION, failure_message
from .forms import QuestionForm
from .models import AssistantMessage
from .tasks import answer

PAGE_SIZE = 10
STALE_AFTER = timedelta(minutes=5)
Status = AssistantMessage.Status
LEGAL_CATEGORIES = ("legal", "mixed")
SUGGESTIONS = (
    {
        "title": "Firma mea",
        "icon": "i-building",
        "items": (
            {"icon": "i-trend", "text": "Ce s-a întâmplat cu veniturile luna aceasta?"},
            {"icon": "i-wallet", "text": "Ce cheltuieli au crescut luna aceasta?"},
            {"icon": "i-receipt", "text": "Ce facturi sunt depășite?"},
            {"icon": "i-box", "text": "Ce produse au stoc redus?"},
            {"icon": "i-alert", "text": "Ce riscuri financiare ar trebui să verific?"},
        ),
    },
    {
        "title": "Legislație",
        "icon": "i-scale",
        "items": (
            {"icon": "i-book", "text": "Ce prevede legislația despre impozitul pe profit?"},
            {"icon": "i-book", "text": "Ce spune legislația despre cotele de TVA?"},
            {"icon": "i-book", "text": "Ce obligații fiscale s-ar putea aplica firmei mele?"},
        ),
    },
)


def _is_enabled():
    policy = AIBudgetPolicy.objects.first()
    return policy is not None and OPERATION in policy.allowed_operations


def _expire_stale(user_id):
    """A lost task must not leave a question waiting forever."""
    AssistantMessage.objects.filter(
        user_id=user_id, status=Status.PENDING, created_at__lt=timezone.now() - STALE_AFTER
    ).update(status=Status.FAILED, failure_code="timed_out", completed_at=timezone.now())


def _day_label(moment, today):
    day = timezone.localtime(moment).date()
    if day == today:
        return "Azi"
    if day == today - timedelta(days=1):
        return "Ieri"
    return day.strftime("%d.%m.%Y")


def _decorate(message, *, today, is_open=False):
    message.failure_text = failure_message(message.failure_code)
    message.day_label = _day_label(message.created_at, today)
    message.is_open = is_open
    return message


def _history(request, user_id):
    search = request.GET.get("q", "").strip()
    kind = request.GET.get("tip", "")
    rows = AssistantMessage.objects.filter(user_id=user_id).order_by("-created_at")
    if search:
        rows = rows.filter(Q(question__icontains=search) | Q(answer_text__icontains=search))
    if kind == "legislatie":
        rows = rows.filter(category__in=LEGAL_CATEGORIES)
    elif kind == "firma":
        rows = rows.exclude(category__in=LEGAL_CATEGORIES)
    page = page_of(request, rows, size=PAGE_SIZE)
    today = timezone.localdate()
    for index, message in enumerate(page):
        # The newest answer is open; older ones stay one line each, to scan the list.
        _decorate(message, today=today, is_open=index == 0 and page.number == 1)
    return {"page": page, "search": search, "kind": kind}


@requires(roles.USE_AI)
def chat(request, tenant_id):
    user_id = request.user.pk
    _expire_stale(user_id)
    enabled = _is_enabled()
    waiting = AssistantMessage.objects.filter(user_id=user_id, status=Status.PENDING).exists()
    form = QuestionForm(request.POST or None)
    if request.method == "POST" and enabled and not waiting and form.is_valid():
        message = AssistantMessage.objects.create(
            tenant_id=tenant_id, user_id=user_id, question=form.cleaned_data["question"].strip()
        )
        record_tenant_event(
            "assistant.question",
            actor_user_id=user_id,
            metadata={"message_id": str(message.pk)},
        )
        enqueue(answer, message_id=str(message.pk))
        return redirect("tenant:assistant", tenant_id=tenant_id)
    context = {**_history(request, user_id), "enabled": enabled}
    if is_htmx(request):
        return render(request, "assistant/_history.html", context)
    return render(
        request,
        "assistant/chat.html",
        {
            **context,
            "form": form,
            "waiting": waiting,
            "suggestions": SUGGESTIONS,
            "has_history": AssistantMessage.objects.filter(user_id=user_id).exists(),
        },
    )


@requires(roles.USE_AI)
def message_status(request, tenant_id, pk):
    """Polled while an answer is being prepared. Row-level security hides other people's rows."""
    _expire_stale(request.user.pk)
    message = get_object_or_404(AssistantMessage, pk=pk)
    _decorate(message, today=timezone.localdate(), is_open=True)
    response = render(request, "assistant/_message.html", {"message": message})
    if not message.is_pending and is_htmx(request):
        # The question box is hidden while waiting, so the finished page must come back whole.
        response["HX-Refresh"] = "true"
    return response


@require_POST
@requires(roles.USE_AI)
def clear_history(request, tenant_id):
    AssistantMessage.objects.filter(user_id=request.user.pk).exclude(status=Status.PENDING).delete()
    record_tenant_event("assistant.history_cleared", actor_user_id=request.user.pk)
    messages.success(request, "Istoricul tău a fost șters.")
    return redirect("tenant:assistant", tenant_id=tenant_id)
