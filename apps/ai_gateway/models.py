import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.db.constraints import TenantFK
from apps.tenants.models import TenantOwnedModel

RATE = {"max_digits": 12, "decimal_places": 6}
MONEY = {"max_digits": 18, "decimal_places": 8}
ZERO = Decimal("0")


class AIProvider(models.Model):
    """Global catalog: the application reads it, only owner credentials write it."""

    key = models.CharField(primary_key=True, max_length=40)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.key


class AIModel(models.Model):
    key = models.CharField(primary_key=True, max_length=100)
    provider = models.ForeignKey(AIProvider, on_delete=models.PROTECT)
    provider_model_name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.key


class AIModelPricing(models.Model):
    """Historical prices per million tokens. Immutable: a new price is a new row."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model = models.ForeignKey(AIModel, on_delete=models.PROTECT, related_name="prices")
    effective_from = models.DateTimeField()
    currency = models.CharField(max_length=3)
    input_per_mtok = models.DecimalField(**RATE)
    cached_read_per_mtok = models.DecimalField(**RATE)
    cache_write_30m_per_mtok = models.DecimalField(**RATE)
    cache_write_12h_per_mtok = models.DecimalField(**RATE)
    output_per_mtok = models.DecimalField(**RATE)
    source_url = models.CharField(max_length=500)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["model", "effective_from"], name="pricing_model_effective_uniq"
            ),
        ]

    def __str__(self):
        return f"{self.model_id} @ {self.effective_from:%Y-%m-%d}"


class AIExchangeRate(models.Model):
    """For GBP and RON reporting. Entered by an operator with its source, never assumed."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    base_currency = models.CharField(max_length=3)
    quote_currency = models.CharField(max_length=3)
    rate = models.DecimalField(max_digits=18, decimal_places=8)
    effective_date = models.DateField()
    source_url = models.CharField(max_length=500)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["base_currency", "quote_currency", "effective_date"],
                name="exchange_rate_day_uniq",
            ),
        ]

    def __str__(self):
        return f"{self.base_currency}/{self.quote_currency} {self.effective_date}"


class AIOperation(models.Model):
    key = models.CharField(primary_key=True, max_length=80)
    name = models.CharField(max_length=200)
    default_model = models.ForeignKey(AIModel, null=True, blank=True, on_delete=models.PROTECT)
    capability = models.CharField(max_length=60, default="use_ai")
    allowed_variables = models.JSONField(default=list)
    max_input_bytes = models.PositiveIntegerField(default=20000)
    max_output_tokens = models.PositiveIntegerField(default=500)
    output_schema = models.JSONField(null=True, blank=True)
    cacheable = models.BooleanField(default=False)
    cache_ttl_seconds = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.key


class PromptTemplateVersion(models.Model):
    """Text is immutable, so an old answer can always be traced to its exact prompt."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    operation = models.ForeignKey(AIOperation, on_delete=models.PROTECT, related_name="prompts")
    version = models.PositiveIntegerField()
    system_template = models.TextField()
    user_template = models.TextField()
    is_active = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["operation", "version"], name="prompt_version_uniq"),
            models.UniqueConstraint(
                fields=["operation"],
                condition=models.Q(is_active=True),
                name="prompt_one_active_per_operation",
            ),
        ]

    def __str__(self):
        return f"{self.operation_id} v{self.version}"


class AIBudgetPolicy(TenantOwnedModel):
    """Limits for a tenant. Only platform staff can change them. No row means no AI."""

    currency = models.CharField(max_length=3, default="USD")
    monthly_limit = models.DecimalField(**MONEY)
    overage_authorised = models.BooleanField(default=False)
    overage_limit = models.DecimalField(default=ZERO, **MONEY)
    max_cost_per_request = models.DecimalField(**MONEY)
    max_output_tokens = models.PositiveIntegerField(default=1000)
    user_daily_limit = models.DecimalField(null=True, blank=True, **MONEY)
    user_monthly_limit = models.DecimalField(null=True, blank=True, **MONEY)
    requests_per_minute = models.PositiveIntegerField(default=30)
    billing_anchor_day = models.PositiveSmallIntegerField(default=1)
    allowed_models = models.JSONField(default=list)
    allowed_operations = models.JSONField(default=list)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            models.UniqueConstraint(fields=["tenant"], name="ai_policy_one_per_tenant"),
        ]

    def __str__(self):
        return f"Politică AI {self.tenant_id}"


class AIBudget(TenantOwnedModel):
    """One row per billing period. Its row lock serialises every reservation of a tenant."""

    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    currency = models.CharField(max_length=3)
    # A database trigger copies the limits from the policy on insert.
    limit_amount = models.DecimalField(default=ZERO, **MONEY)
    overage_limit = models.DecimalField(default=ZERO, **MONEY)
    spent = models.DecimalField(default=ZERO, **MONEY)
    reserved = models.DecimalField(default=ZERO, **MONEY)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            models.UniqueConstraint(
                fields=["tenant", "period_start"], name="ai_budget_period_uniq"
            ),
            models.CheckConstraint(
                condition=models.Q(spent__gte=0) & models.Q(reserved__gte=0),
                name="ai_budget_not_negative",
            ),
        ]

    def __str__(self):
        return f"Buget AI {self.tenant_id} {self.period_start:%Y-%m}"


class AIBudgetAlert(TenantOwnedModel):
    budget = models.ForeignKey(
        AIBudget, on_delete=models.DO_NOTHING, db_constraint=False, related_name="alerts"
    )
    threshold = models.PositiveSmallIntegerField()
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            models.UniqueConstraint(
                fields=["tenant", "budget", "threshold"], name="ai_alert_once_per_threshold"
            ),
            TenantFK(column="budget_id", to_table="ai_gateway_aibudget", name="ai_alert_budget_fk"),
        ]

    def __str__(self):
        return f"{self.threshold}%"


class AIUsageReservation(TenantOwnedModel):
    class Status(models.TextChoices):
        RESERVED = "reserved", "Rezervat"
        COMMITTED = "committed", "Finalizat"
        RELEASED = "released", "Eliberat"
        # The provider may have charged us: the money stays held until a person resolves it.
        UNKNOWN = "unknown", "Rezultat necunoscut"

    budget = models.ForeignKey(
        AIBudget, on_delete=models.DO_NOTHING, db_constraint=False, related_name="+"
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    operation = models.ForeignKey(AIOperation, on_delete=models.PROTECT, related_name="+")
    model = models.ForeignKey(AIModel, on_delete=models.PROTECT, related_name="+")
    pricing = models.ForeignKey(AIModelPricing, on_delete=models.PROTECT, related_name="+")
    prompt = models.ForeignKey(PromptTemplateVersion, on_delete=models.PROTECT, related_name="+")
    idempotency_key = models.CharField(max_length=100)
    max_cost = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.RESERVED)
    failure_reason = models.CharField(max_length=60, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"], name="ai_reservation_idempotency_uniq"
            ),
            TenantFK(
                column="budget_id", to_table="ai_gateway_aibudget", name="ai_reservation_budget_fk"
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "user", "created_at"], name="ai_reservation_user_idx"),
            models.Index(fields=["status"], name="ai_reservation_status_idx"),
        ]

    def __str__(self):
        return f"{self.idempotency_key} / {self.status}"


class AIUsageEvent(TenantOwnedModel):
    """Append-only record of one attempt. It never contains the prompt or the answer."""

    class Status(models.TextChoices):
        COMPLETED = "completed", "Finalizat"
        CACHE_HIT = "cache_hit", "Din cache"
        INCOMPLETE = "incomplete", "Incomplet"
        REFUSED = "refused", "Refuzat de model"
        INVALID_OUTPUT = "invalid_output", "Rezultat invalid"
        USAGE_MISSING = "usage_missing", "Consum neraportat"

    reservation = models.ForeignKey(
        AIUsageReservation, null=True, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="+",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    operation = models.ForeignKey(AIOperation, on_delete=models.PROTECT, related_name="+")
    model = models.ForeignKey(AIModel, on_delete=models.PROTECT, related_name="+")
    pricing = models.ForeignKey(AIModelPricing, on_delete=models.PROTECT, related_name="+")
    prompt = models.ForeignKey(PromptTemplateVersion, on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=20, choices=Status.choices)
    input_tokens = models.PositiveIntegerField(default=0)
    cached_tokens = models.PositiveIntegerField(default=0)
    cache_write_30m_tokens = models.PositiveIntegerField(default=0)
    cache_write_12h_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    provider_usage = models.JSONField(default=dict)
    provider_request_id = models.CharField(max_length=200, blank=True)
    estimated_cost = models.DecimalField(**MONEY)
    actual_cost = models.DecimalField(**MONEY)
    currency = models.CharField(max_length=3)
    latency_ms = models.PositiveIntegerField(default=0)
    retry_count = models.PositiveSmallIntegerField(default=0)
    is_synthetic = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            TenantFK(
                column="reservation_id",
                to_table="ai_gateway_aiusagereservation",
                name="ai_event_reservation_fk",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "user", "created_at"], name="ai_event_user_idx"),
            models.Index(fields=["tenant", "created_at"], name="ai_event_tenant_idx"),
        ]

    def __str__(self):
        return f"{self.operation_id} / {self.status}"


class AIStoredResponse(TenantOwnedModel):
    """Answers for idempotent replay and caching: tenant-isolated, and purged after a set time."""

    reservation = models.ForeignKey(
        AIUsageReservation, null=True, on_delete=models.DO_NOTHING, db_constraint=False,
        related_name="+",
    )
    cache_key = models.CharField(max_length=64)
    output_text = models.TextField()
    is_synthetic = models.BooleanField(default=False)
    expires_at = models.DateTimeField()
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            TenantFK(
                column="reservation_id",
                to_table="ai_gateway_aiusagereservation",
                name="ai_stored_reservation_fk",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "cache_key"], name="ai_stored_cache_idx"),
        ]

    def __str__(self):
        return f"Răspuns {self.pk}"


class AIProviderReconciliation(models.Model):
    """Provider invoice against our calculation. Platform-only: the application has no access."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    provider = models.ForeignKey(AIProvider, on_delete=models.PROTECT)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    currency = models.CharField(max_length=3)
    reported_cost = models.DecimalField(**MONEY)
    calculated_cost = models.DecimalField(**MONEY)
    note = models.TextField(blank=True)
    recorded_by_id = models.UUIDField()
    recorded_at = models.DateTimeField(default=timezone.now, editable=False)

    def __str__(self):
        return f"{self.provider_id} {self.period_start:%Y-%m}"
