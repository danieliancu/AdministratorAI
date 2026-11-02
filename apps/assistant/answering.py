"""Answer one question: facts and evidence from the application, explanation from the model."""

import json
import logging

from django.utils import timezone

from apps.ai_gateway.gateway import (
    AIDenied,
    AIError,
    AIInvalidOutput,
    AIOutcomeUnknown,
    AIProviderFailed,
    AIRequest,
    AIRequestInProgress,
    execute,
)
from apps.core.db.scope import db_scope
from apps.reports import figures
from apps.tenants import roles
from apps.tenants.access import load_tenant_access

from . import grounding, legal
from .facts import build_facts
from .models import AssistantMessage
from .understanding import understand

logger = logging.getLogger(__name__)

OPERATION = "assistant.answer"
Status = AssistantMessage.Status

ALWAYS = (
    "Cifrele provin doar din ce a fost introdus sau importat în aplicație. Pot fi incomplete "
    "și nu sunt rezultate contabile."
)
UNVERIFIED_LAW = (
    "Răspuns generat automat, neverificat de un specialist. Nu este consultanță juridică sau "
    "fiscală."
)
NO_RULES = "Regulile fiscale și calendarul fiscal nu sunt încă disponibile în aplicație."
TAX_ANSWER = (
    "Nu calculez impozite, taxe sau contribuții: aceste calcule trebuie făcute de un motor de "
    "reguli verificat de un specialist, care nu este încă disponibil. Mai jos sunt doar cifrele "
    "înregistrate, ca punct de plecare pentru contabil."
)
GROUNDING_ANSWER = (
    "Răspunsul generat conținea cifre care nu se regăsesc în datele firmei, așa că nu îl "
    "afișăm. Cifrele de mai jos sunt calculate direct de aplicație."
)
NO_SOURCE = (
    "Nu am găsit informația în datele firmei sau în legislația disponibilă în aplicație. "
    "Asistentul răspunde numai din aceste două surse."
)
FAILURES = {
    "ai_not_enabled": "Asistentul nu este activat pentru această firmă.",
    "operation_not_in_plan": "Asistentul nu este activat pentru această firmă.",
    "model_not_in_plan": "Asistentul nu este disponibil momentan.",
    "budget_exhausted": "Asistentul nu mai este disponibil în această perioadă pentru firmă.",
    "user_daily_limit": "Ai atins limita de utilizare a asistentului. Încearcă mai târziu.",
    "user_monthly_limit": "Ai atins limita de utilizare a asistentului.",
    "rate_limited": "Prea multe întrebări într-un timp scurt. Încearcă din nou peste un minut.",
    "input_too_large": "Întrebarea are nevoie de prea multe date. Alege o perioadă mai scurtă.",
    "request_too_expensive": "Întrebarea are nevoie de prea multe date. Alege altă perioadă.",
}
UNAVAILABLE = "Asistentul nu este disponibil momentan. Cifrele din rapoarte nu sunt afectate."
UNCLEAR = (
    "Nu știm dacă răspunsul a fost generat, din cauza unei probleme de conexiune. "
    "Încearcă din nou peste câteva minute."
)
INVALID = "Răspunsul generat nu a trecut verificările, așa că nu îl afișăm. Încearcă din nou."


def failure_message(code):
    if code == "outcome_unknown":
        return UNCLEAR
    if code == "invalid_output":
        return INVALID
    return FAILURES.get(code, UNAVAILABLE)


def _scope(message_tenant, user_id):
    return db_scope(tenant_id=message_tenant, user_id=user_id)


def _fail(tenant_id, user_id, message_id, code):
    with _scope(tenant_id, user_id):
        AssistantMessage.objects.filter(pk=message_id).update(
            status=Status.FAILED, failure_code=code, completed_at=timezone.now()
        )


def _prepare(message, tenant_id, user_id):
    """Everything the application knows, gathered before any model is involved."""
    access = load_tenant_access(user_id)
    if access is None or not access.is_active or not access.can(roles.USE_AI):
        return None
    today = timezone.localdate()
    seen = understand(message.question, today)
    message.category = seen.category
    message.period_start, message.period_end = seen.start, seen.end
    limitations = [ALWAYS]
    assumptions = []
    if seen.period_assumed:
        assumptions.append(f"Nu ai indicat o perioadă, așa că am folosit {seen.period_label}.")
    facts = build_facts(seen) if access.can(roles.VIEW_FINANCE) else []
    if not figures.vat_status_is_confirmed_payer():
        limitations.append(
            "Statutul de plătitor de TVA nu este confirmat, iar sumele sunt afișate fără TVA."
        )
    empty = figures.empty_months(seen.start, min(seen.end, today))
    if empty["sales"]:
        limitations.append(f"Fără vânzări înregistrate în: {', '.join(empty['sales'])}.")
    if empty["expenses"]:
        limitations.append(f"Fără cheltuieli înregistrate în: {', '.join(empty['expenses'])}.")
    citations = []
    if seen.wants_legal:
        citations, legal_limits = legal.gather(message.question, min(seen.end, today))
        limitations.extend(legal_limits)
        limitations.extend([UNVERIFIED_LAW, NO_RULES])
    message.facts = facts
    message.limitations = limitations
    message.assumptions = assumptions
    message.save()
    return seen, citations


def _model_variables(message, seen, citations):
    evidence = [
        {
            "id": c["id"],
            "act": c["citation"],
            "titlu": c["title"],
            "articol": c["article"],
            "alineat": c["paragraph"],
            "autoritate": c["authority"],
            "aplicabil_de_la": c["valid_from"],
            "aplicabil_pana_la": c["valid_to"],
            "avertismente": c["warnings"],
            "text": c["text"],
        }
        for c in citations
    ]
    # JSON keeps every piece of data inside a string, so it cannot pose as a new section.
    return {
        "question": json.dumps(message.question, ensure_ascii=False),
        "period": seen.period_label,
        "facts": json.dumps(message.facts, ensure_ascii=False),
        "evidence": json.dumps(evidence, ensure_ascii=False),
    }


def _apply_answer(message, parsed, citations):
    """Keep only what can be traced. The model chooses among facts; it cannot add any."""
    known_facts = {fact["id"] for fact in message.facts}
    known_evidence = {citation["id"]: citation for citation in citations}
    message.used_fact_ids = [i for i in parsed["fact_ids"] if i in known_facts]
    cited = [known_evidence[i] for i in parsed["evidence_ids"] if i in known_evidence]
    invented_citation = len(cited) != len(parsed["evidence_ids"])

    written = [
        parsed["answer"],
        *parsed["assumptions"],
        *parsed["limitations"],
        *parsed["suggested_actions"],
    ]
    supplied = [
        message.question,
        message.assumptions and " ".join(message.assumptions) or "",
        *(f"{f['label']} {f['value']} {f['note']}" for f in message.facts),
        *(
            f"{c['citation']} {c['title']} {c['article']} {c['paragraph']} {c['valid_from']} "
            f"{c['valid_to']} {c['text']}"
            for c in citations
        ),
        f"{message.period_start:%d.%m.%Y} {message.period_end:%d.%m.%Y}",
    ]
    unknown = grounding.unknown_numbers(written, grounding.known_values(supplied))
    if unknown or invented_citation:
        logger.warning(
            "Assistant answer withheld: %d unknown numbers, invented citation: %s",
            len(unknown),
            invented_citation,
        )
        message.grounding_failed = True
        message.answer_text = GROUNDING_ANSWER
        message.used_fact_ids = [fact["id"] for fact in message.facts[:12]]
        return
    if not message.used_fact_ids and not cited:
        # Decided here, not left to the model: with no source behind it, a text is not shown.
        message.answer_text = NO_SOURCE
        return
    message.answer_text = parsed["answer"]
    message.citations = cited
    message.assumptions = [*message.assumptions, *parsed["assumptions"]]
    message.limitations = [*message.limitations, *parsed["limitations"]]
    message.actions = parsed["suggested_actions"]


def answer_message(message_id, *, tenant_id, user_id, adapter=None):
    with _scope(tenant_id, user_id):
        message = AssistantMessage.objects.filter(pk=message_id, status=Status.PENDING).first()
        if message is None:
            return None
        prepared = _prepare(message, tenant_id, user_id)
        if prepared is None:
            message.status = Status.FAILED
            message.failure_code = "not_permitted"
            message.completed_at = timezone.now()
            message.save()
            return message
        seen, citations = prepared
        if seen.category == "tax_calculation":
            # Decided before the model: a tax figure must never come from an LLM.
            message.answer_text = TAX_ANSWER
            message.used_fact_ids = [fact["id"] for fact in message.facts[:12]]
            message.status = Status.COMPLETED
            message.completed_at = timezone.now()
            message.save()
            return message
        variables = _model_variables(message, seen, citations)

    gateway_kwargs = {"adapter": adapter} if adapter else {}
    try:
        result = execute(
            AIRequest(
                tenant_id=tenant_id,
                user_id=user_id,
                operation=OPERATION,
                idempotency_key=f"assistant:{message_id}",
                variables=variables,
            ),
            **gateway_kwargs,
        )
    except AIDenied as denied:
        _fail(tenant_id, user_id, message_id, denied.reason)
        return None
    except (AIOutcomeUnknown, AIRequestInProgress):
        _fail(tenant_id, user_id, message_id, "outcome_unknown")
        return None
    except AIInvalidOutput:
        _fail(tenant_id, user_id, message_id, "invalid_output")
        return None
    except AIProviderFailed:
        _fail(tenant_id, user_id, message_id, "provider_failed")
        return None
    except AIError:
        logger.exception("Assistant failed")
        _fail(tenant_id, user_id, message_id, "provider_failed")
        return None

    try:
        parsed = json.loads(result.output_text)
    except ValueError:
        # Only a replayed request can get here: fresh output was validated by the gateway.
        _fail(tenant_id, user_id, message_id, "invalid_output")
        return None
    with _scope(tenant_id, user_id):
        message = AssistantMessage.objects.get(pk=message_id)
        _apply_answer(message, parsed, citations)
        message.used_model = True
        message.is_synthetic = result.is_synthetic
        message.status = Status.COMPLETED
        message.completed_at = timezone.now()
        message.save()
    return message
