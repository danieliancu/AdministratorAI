"""Embeddings for platform-owned text, under a platform budget instead of a tenant's.

Same rules as the gateway: reserve first, call outside any transaction, and hold the money
if the outcome is uncertain. Runs on the given database alias.
"""

import time
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from django.db import transaction
from django.utils import timezone

from .gateway import billing_period
from .models import AIModel, AIModelPricing, AIPlatformBudget, AIPlatformUsage
from .pricing import MILLION, STEP
from .providers import get_adapter
from .providers.base import ProviderError, ProviderNotProcessed


class EmbeddingUnavailable(Exception):
    """No budget, price or key. Callers keep working without semantic search."""


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list
    cost: Decimal
    is_synthetic: bool


def _cost(rate, tokens):
    return (Decimal(tokens) * rate / MILLION).quantize(STEP, rounding=ROUND_CEILING)


def _reserve(model, pricing, max_cost, purpose, using):
    start, end = billing_period(timezone.now(), 1)
    with transaction.atomic(using=using):
        latest = AIPlatformBudget.objects.using(using).order_by("-period_start").first()
        if latest is None:
            raise EmbeddingUnavailable("no_platform_budget")
        if pricing.currency != latest.currency:
            raise EmbeddingUnavailable("currency_mismatch")
        AIPlatformBudget.objects.using(using).bulk_create(
            [
                AIPlatformBudget(
                    period_start=start,
                    period_end=end,
                    currency=latest.currency,
                    limit_amount=latest.limit_amount,
                )
            ],
            ignore_conflicts=True,
        )
        budget = (
            AIPlatformBudget.objects.using(using).select_for_update().get(period_start=start)
        )
        if budget.spent + budget.reserved + max_cost > budget.limit_amount:
            raise EmbeddingUnavailable("platform_budget_exhausted")
        usage = AIPlatformUsage.objects.using(using).create(
            budget=budget,
            model=model,
            pricing=pricing,
            purpose=purpose,
            estimated_cost=max_cost,
            currency=pricing.currency,
        )
        budget.reserved += max_cost
        budget.save(using=using, update_fields=["reserved"])
    return usage


def _settle(usage, *, status, charge=Decimal(0), tokens=0, synthetic=False, latency=0, using):
    with transaction.atomic(using=using):
        budget = (
            AIPlatformBudget.objects.using(using).select_for_update().get(pk=usage.budget_id)
        )
        budget.reserved -= usage.estimated_cost
        budget.spent += charge
        budget.save(using=using, update_fields=["reserved", "spent"])
        usage.status = status
        usage.actual_cost = charge
        usage.input_tokens = tokens
        usage.is_synthetic = synthetic
        usage.latency_ms = latency
        usage.save(
            using=using,
            update_fields=["status", "actual_cost", "input_tokens", "is_synthetic", "latency_ms"],
        )


def embed_texts(texts, *, model_key, using, purpose, adapter=None):
    if transaction.get_connection(using).in_atomic_block:
        raise EmbeddingUnavailable("inside_transaction")
    model = (
        AIModel.objects.using(using)
        .select_related("provider")
        .filter(pk=model_key, is_active=True, provider__is_active=True)
        .first()
    )
    if model is None:
        raise EmbeddingUnavailable("model_unavailable")
    pricing = (
        AIModelPricing.objects.using(using)
        .filter(model=model, effective_from__lte=timezone.now())
        .order_by("-effective_from")
        .first()
    )
    if pricing is None:
        raise EmbeddingUnavailable("no_pricing")

    # Upper bound: one token per UTF-8 byte.
    max_cost = _cost(pricing.input_per_mtok, sum(len(t.encode()) for t in texts))
    usage = _reserve(model, pricing, max_cost, purpose, using)

    provider = adapter or get_adapter(model.provider_id)
    started = time.monotonic()
    try:
        result = provider.embed(model.provider_model_name, texts)
    except ProviderNotProcessed as exc:
        _settle(usage, status=AIPlatformUsage.Status.RELEASED, using=using)
        raise EmbeddingUnavailable(type(exc).__name__) from exc
    except ProviderError as exc:
        AIPlatformUsage.objects.using(using).filter(pk=usage.pk).update(
            status=AIPlatformUsage.Status.UNKNOWN
        )
        raise EmbeddingUnavailable("outcome_unknown") from exc
    latency = int((time.monotonic() - started) * 1000)
    charge = (
        _cost(pricing.input_per_mtok, result.input_tokens)
        if result.usage_known
        else usage.estimated_cost
    )
    _settle(
        usage,
        status=AIPlatformUsage.Status.COMMITTED,
        charge=charge,
        tokens=result.input_tokens,
        synthetic=result.is_synthetic,
        latency=latency,
        using=using,
    )
    return EmbeddingResult(result.vectors, charge, result.is_synthetic)
