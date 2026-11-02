"""The single path to any AI provider.

Each step opens its own short database scope, and the provider call runs outside any
transaction: a reservation must be committed before the call so concurrent requests see it,
and no row lock may be held during a slow network call.
"""

import hashlib
import json
import logging
import string
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import jsonschema
from django.conf import settings
from django.db import connection
from django.db.models import Sum
from django.utils import timezone

from apps.audit.services import record_tenant_event
from apps.core.db.scope import db_scope
from apps.core.throttle import Throttled, hit
from apps.tenants.access import load_tenant_access

from . import pricing as pricing_rules
from .models import (
    AIBudget,
    AIBudgetAlert,
    AIBudgetPolicy,
    AIModelPricing,
    AIOperation,
    AIStoredResponse,
    AIUsageEvent,
    AIUsageReservation,
    PromptTemplateVersion,
)
from .providers import get_adapter
from .providers.base import (
    ProviderNotProcessed,
    ProviderRequest,
    ProviderRetryable,
)

logger = logging.getLogger(__name__)

ALERT_THRESHOLDS = (70, 90, 100)
Status = AIUsageReservation.Status


class AIError(Exception):
    pass


class GatewayMisuse(AIError):
    """Raised for a call inside a transaction, which would hide the reservation."""


class AIDenied(AIError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class AIRequestInProgress(AIError):
    pass


class AIOutcomeUnknown(AIError):
    """The provider may have charged us. The reservation stays held."""


class AIProviderFailed(AIError):
    """The provider did not process the request. The reservation was released."""


class AIInvalidOutput(AIError):
    """The answer failed validation. It was charged, and is not returned."""


@dataclass(frozen=True)
class AIRequest:
    tenant_id: object
    user_id: object
    operation: str
    idempotency_key: str
    variables: dict = field(default_factory=dict)


@dataclass(frozen=True)
class AIResult:
    output_text: str
    status: str
    cost: Decimal
    currency: str
    is_synthetic: bool
    from_cache: bool = False
    replayed: bool = False


def billing_period(now, anchor_day):
    """The monthly period containing `now`, starting on the anchor day at midnight UTC."""
    now = now.astimezone(UTC)
    year, month = now.year, now.month
    if now.day < anchor_day:
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    start = datetime(year, month, anchor_day, tzinfo=UTC)
    end_year, end_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return start, datetime(end_year, end_month, anchor_day, tzinfo=UTC)


@dataclass(frozen=True)
class _Plan:
    operation: AIOperation
    policy: AIBudgetPolicy
    prompt: PromptTemplateVersion
    pricing: AIModelPricing
    provider_key: str
    provider_model_name: str
    model_key: str
    system_prompt: str
    user_prompt: str
    max_output_tokens: int
    max_cost: Decimal
    cache_key: str


def _render(template, variables):
    return string.Template(template).substitute(variables)


class AIGateway:
    def __init__(self, sleep=time.sleep, adapter=None):
        self._sleep = sleep
        self._adapter = adapter

    def execute(self, request: AIRequest) -> AIResult:
        if connection.in_atomic_block:
            raise GatewayMisuse("The AI gateway must not run inside a transaction")
        try:
            plan = self._prepare(request)
            self._rate_limit(request, plan)
            cached = self._from_cache(request, plan)
            if cached:
                return cached
            reservation, replay = self._reserve(request, plan)
            if replay:
                return replay
        except AIDenied as denied:
            self._record_denial(request, denied.reason)
            raise
        return self._call_provider(request, plan, reservation)

    def _prepare(self, request):
        with db_scope(tenant_id=request.tenant_id, user_id=request.user_id):
            access = load_tenant_access(request.user_id)
            if access is None or not access.is_active:
                raise AIDenied("no_tenant_access")
            operation = (
                AIOperation.objects.select_related("default_model__provider")
                .filter(pk=request.operation, is_active=True)
                .first()
            )
            if operation is None:
                raise AIDenied("unknown_operation")
            if not access.can(operation.capability):
                raise AIDenied("not_permitted")
            policy = AIBudgetPolicy.objects.filter(tenant_id=request.tenant_id).first()
            if policy is None:
                raise AIDenied("ai_not_enabled")
            if operation.pk not in policy.allowed_operations:
                raise AIDenied("operation_not_in_plan")

            model = operation.default_model
            if model is None or not model.is_active or not model.provider.is_active:
                raise AIDenied("model_unavailable")
            if model.pk not in policy.allowed_models:
                raise AIDenied("model_not_in_plan")
            prices = AIModelPricing.objects.filter(
                model=model, effective_from__lte=timezone.now()
            ).order_by("-effective_from")
            pricing = prices.first()
            if pricing is None:
                raise AIDenied("no_pricing")
            if pricing.currency != policy.currency:
                raise AIDenied("currency_mismatch")
            prompt = PromptTemplateVersion.objects.filter(
                operation=operation, is_active=True
            ).first()
            if prompt is None:
                raise AIDenied("no_active_prompt")

        # Data minimisation: only variables the operation declares can reach the provider.
        if set(request.variables) != set(operation.allowed_variables):
            raise AIDenied("unexpected_variables")
        system_prompt = prompt.system_template
        user_prompt = _render(prompt.user_template, request.variables)
        input_bytes = len(system_prompt.encode()) + len(user_prompt.encode())
        if input_bytes > operation.max_input_bytes:
            raise AIDenied("input_too_large")

        max_output = min(operation.max_output_tokens, policy.max_output_tokens)
        max_cost = pricing_rules.maximum_cost(
            pricing, input_bytes=input_bytes, max_output_tokens=max_output
        )
        if max_cost > policy.max_cost_per_request:
            raise AIDenied("request_too_expensive")

        digest = hashlib.sha256(
            json.dumps(
                [str(request.tenant_id), operation.pk, str(prompt.pk), model.pk, user_prompt]
            ).encode()
        ).hexdigest()
        return _Plan(
            operation=operation,
            policy=policy,
            prompt=prompt,
            pricing=pricing,
            provider_key=model.provider_id,
            provider_model_name=model.provider_model_name,
            model_key=model.pk,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=max_output,
            max_cost=max_cost,
            cache_key=digest,
        )

    def _rate_limit(self, request, plan):
        try:
            hit(
                "ai-tenant",
                request.tenant_id,
                limit=plan.policy.requests_per_minute,
                window=60,
            )
        except Throttled as exc:
            raise AIDenied("rate_limited") from exc

    def _from_cache(self, request, plan):
        if not plan.operation.cacheable:
            return None
        with db_scope(tenant_id=request.tenant_id, user_id=request.user_id):
            stored = AIStoredResponse.objects.filter(
                cache_key=plan.cache_key, expires_at__gt=timezone.now()
            ).first()
            if stored is None:
                return None
            AIUsageEvent.objects.create(
                tenant_id=request.tenant_id,
                user_id=request.user_id,
                operation=plan.operation,
                model_id=plan.model_key,
                pricing=plan.pricing,
                prompt=plan.prompt,
                status=AIUsageEvent.Status.CACHE_HIT,
                estimated_cost=0,
                actual_cost=0,
                currency=plan.pricing.currency,
                is_synthetic=stored.is_synthetic,
            )
        return AIResult(
            output_text=stored.output_text,
            status=AIUsageEvent.Status.CACHE_HIT,
            cost=Decimal(0),
            currency=plan.pricing.currency,
            is_synthetic=stored.is_synthetic,
            from_cache=True,
        )

    def _lock_budget(self, request, plan):
        start, end = billing_period(timezone.now(), plan.policy.billing_anchor_day)
        # The row may not exist yet: ignore_conflicts makes the first insert race harmless.
        AIBudget.objects.bulk_create(
            [
                AIBudget(
                    tenant_id=request.tenant_id,
                    period_start=start,
                    period_end=end,
                    currency=plan.policy.currency,
                )
            ],
            ignore_conflicts=True,
        )
        return AIBudget.objects.select_for_update().get(
            tenant_id=request.tenant_id, period_start=start
        )

    def _user_total(self, request, since):
        """Spent plus still-held amounts. Runs under the budget lock, so it cannot race."""
        held = AIUsageReservation.objects.filter(
            user_id=request.user_id,
            created_at__gte=since,
            status__in=[Status.RESERVED, Status.UNKNOWN],
        ).aggregate(total=Sum("max_cost"))["total"]
        spent = AIUsageEvent.objects.filter(
            user_id=request.user_id, created_at__gte=since
        ).aggregate(total=Sum("actual_cost"))["total"]
        return (held or Decimal(0)) + (spent or Decimal(0))

    def _reserve(self, request, plan):
        policy = plan.policy
        with db_scope(tenant_id=request.tenant_id, user_id=request.user_id):
            budget = self._lock_budget(request, plan)
            existing = AIUsageReservation.objects.filter(
                idempotency_key=request.idempotency_key
            ).first()
            if existing is not None:
                return None, self._replay(existing)

            ceiling = budget.limit_amount + budget.overage_limit
            if budget.spent + budget.reserved + plan.max_cost > ceiling:
                raise AIDenied("budget_exhausted")
            now = timezone.now()
            if policy.user_daily_limit is not None:
                day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
                total = self._user_total(request, day_start)
                if total + plan.max_cost > policy.user_daily_limit:
                    raise AIDenied("user_daily_limit")
            if policy.user_monthly_limit is not None:
                total = self._user_total(request, budget.period_start)
                if total + plan.max_cost > policy.user_monthly_limit:
                    raise AIDenied("user_monthly_limit")

            reservation = AIUsageReservation.objects.create(
                tenant_id=request.tenant_id,
                budget=budget,
                user_id=request.user_id,
                operation=plan.operation,
                model_id=plan.model_key,
                pricing=plan.pricing,
                prompt=plan.prompt,
                idempotency_key=request.idempotency_key,
                max_cost=plan.max_cost,
                currency=plan.pricing.currency,
            )
            budget.reserved += plan.max_cost
            budget.save(update_fields=["reserved"])
        return reservation, None

    def _replay(self, reservation):
        if reservation.status == Status.RESERVED:
            raise AIRequestInProgress(reservation.idempotency_key)
        if reservation.status == Status.UNKNOWN:
            raise AIOutcomeUnknown(reservation.idempotency_key)
        if reservation.status == Status.RELEASED:
            raise AIProviderFailed(reservation.failure_reason or "released")
        stored = AIStoredResponse.objects.filter(reservation=reservation).first()
        event = AIUsageEvent.objects.filter(reservation=reservation).first()
        return AIResult(
            output_text=stored.output_text if stored else "",
            status=event.status if event else Status.COMMITTED,
            cost=Decimal(0),
            currency=reservation.currency,
            is_synthetic=stored.is_synthetic if stored else False,
            replayed=True,
        )

    def _call_provider(self, request, plan, reservation):
        adapter = self._adapter or get_adapter(plan.provider_key)
        provider_request = ProviderRequest(
            provider_model_name=plan.provider_model_name,
            system_prompt=plan.system_prompt,
            user_prompt=plan.user_prompt,
            max_output_tokens=plan.max_output_tokens,
            output_schema=plan.operation.output_schema,
        )
        started = time.monotonic()
        attempt = 0
        while True:
            try:
                result = adapter.complete(provider_request)
                break
            except ProviderRetryable as exc:
                if attempt >= settings.AAI_AI_MAX_RETRIES:
                    self._release(request, reservation, "rate_limited_by_provider")
                    raise AIProviderFailed("rate_limited_by_provider") from exc
                self._sleep(0.5 * 2**attempt)
                attempt += 1
            except ProviderNotProcessed as exc:
                self._release(request, reservation, type(exc).__name__)
                raise AIProviderFailed(type(exc).__name__) from exc
            except Exception as exc:
                # Timeouts, cancellations and surprises alike: assume we may have been charged.
                self._mark_unknown(request, reservation, type(exc).__name__)
                raise AIOutcomeUnknown(type(exc).__name__) from exc
        latency_ms = int((time.monotonic() - started) * 1000)
        return self._commit(request, plan, reservation, result, latency_ms, attempt)

    def _settle(self, reservation, *, status, charge, failure_reason=""):
        """Moves the held amount out of `reserved`, and adds the charge to `spent`."""
        budget = AIBudget.objects.select_for_update().get(pk=reservation.budget_id)
        current = AIUsageReservation.objects.select_for_update().get(pk=reservation.pk)
        if current.status != Status.RESERVED:
            raise GatewayMisuse(f"Reservation already {current.status}")
        budget.reserved -= current.max_cost
        budget.spent += charge
        budget.save(update_fields=["reserved", "spent"])
        current.status = status
        current.failure_reason = failure_reason
        current.resolved_at = timezone.now()
        current.save(update_fields=["status", "failure_reason", "resolved_at"])
        return budget

    def _release(self, request, reservation, reason):
        with db_scope(tenant_id=request.tenant_id, user_id=request.user_id):
            self._settle(reservation, status=Status.RELEASED, charge=0, failure_reason=reason)

    def _mark_unknown(self, request, reservation, reason):
        """Keeps the money held: only a person, or reconciliation, may release it."""
        logger.error("AI outcome unknown for reservation %s: %s", reservation.pk, reason)
        with db_scope(tenant_id=request.tenant_id, user_id=request.user_id):
            current = AIUsageReservation.objects.select_for_update().get(pk=reservation.pk)
            current.status = Status.UNKNOWN
            current.failure_reason = reason
            current.save(update_fields=["status", "failure_reason"])

    def _commit(self, request, plan, reservation, result, latency_ms, retries):
        status, valid = self._classify(plan, result)
        if result.usage_known:
            charge = pricing_rules.actual_cost(
                plan.pricing,
                input_tokens=result.input_tokens,
                cached=result.cached_tokens,
                write_30m=result.cache_write_30m_tokens,
                write_12h=result.cache_write_12h_tokens,
                output_tokens=result.output_tokens,
            )
        else:
            # Billed something we cannot see: charge the most it could have been.
            charge = reservation.max_cost
        with db_scope(tenant_id=request.tenant_id, user_id=request.user_id):
            budget = self._settle(reservation, status=Status.COMMITTED, charge=charge)
            AIUsageEvent.objects.create(
                tenant_id=request.tenant_id,
                reservation=reservation,
                user_id=request.user_id,
                operation=plan.operation,
                model_id=plan.model_key,
                pricing=plan.pricing,
                prompt=plan.prompt,
                status=status,
                input_tokens=result.input_tokens,
                cached_tokens=result.cached_tokens,
                cache_write_30m_tokens=result.cache_write_30m_tokens,
                cache_write_12h_tokens=result.cache_write_12h_tokens,
                output_tokens=result.output_tokens,
                provider_usage=result.raw_usage,
                provider_request_id=result.request_id,
                estimated_cost=reservation.max_cost,
                actual_cost=charge,
                currency=reservation.currency,
                latency_ms=latency_ms,
                retry_count=retries,
                is_synthetic=result.is_synthetic,
            )
            self._record_alerts(budget)
            if valid:
                self._store(request, plan, reservation, result)
        if not valid:
            raise AIInvalidOutput(status)
        return AIResult(
            output_text=result.output_text,
            status=status,
            cost=charge,
            currency=reservation.currency,
            is_synthetic=result.is_synthetic,
        )

    def _classify(self, plan, result):
        if result.status == "refused":
            return AIUsageEvent.Status.REFUSED, False
        if result.status != "completed":
            return AIUsageEvent.Status.INCOMPLETE, False
        if plan.operation.output_schema:
            try:
                jsonschema.validate(json.loads(result.output_text), plan.operation.output_schema)
            except (ValueError, jsonschema.ValidationError):
                return AIUsageEvent.Status.INVALID_OUTPUT, False
        if not result.usage_known:
            return AIUsageEvent.Status.USAGE_MISSING, True
        return AIUsageEvent.Status.COMPLETED, True

    def _store(self, request, plan, reservation, result):
        now = timezone.now()
        AIStoredResponse.objects.filter(expires_at__lte=now).delete()
        retention = timedelta(days=settings.AAI_AI_RESPONSE_RETENTION_DAYS)
        if plan.operation.cacheable:
            retention = timedelta(seconds=plan.operation.cache_ttl_seconds)
        AIStoredResponse.objects.create(
            tenant_id=request.tenant_id,
            reservation=reservation,
            cache_key=plan.cache_key,
            output_text=result.output_text,
            is_synthetic=result.is_synthetic,
            expires_at=now + retention,
        )

    def _record_alerts(self, budget):
        if budget.limit_amount <= 0:
            return
        used = (budget.spent / budget.limit_amount) * 100
        crossed = [t for t in ALERT_THRESHOLDS if used >= t]
        new = [AIBudgetAlert(tenant_id=budget.tenant_id, budget=budget, threshold=t)
               for t in crossed]
        AIBudgetAlert.objects.bulk_create(new, ignore_conflicts=True)

    def _record_denial(self, request, reason):
        # Runs after the failed scope: an event written inside it would roll back with it.
        try:
            with db_scope(tenant_id=request.tenant_id, user_id=request.user_id):
                record_tenant_event(
                    "ai.denied",
                    actor_user_id=request.user_id,
                    metadata={"reason": reason, "operation": request.operation},
                )
        except Exception:
            logger.exception("Could not record an AI denial")


def execute(request: AIRequest, **kwargs) -> AIResult:
    return AIGateway(**kwargs).execute(request)
