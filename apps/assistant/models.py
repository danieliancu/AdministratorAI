from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.tenants.models import TenantOwnedModel


class AssistantMessage(TenantOwnedModel):
    """One question and its answer. Row-level security limits it to the person who asked."""

    class Status(models.TextChoices):
        PENDING = "pending", "Se pregătește"
        COMPLETED = "completed", "Finalizat"
        FAILED = "failed", "Eșuat"

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    question = models.CharField(max_length=1000)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    category = models.CharField(max_length=30, blank=True)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    answer_text = models.TextField(blank=True)
    assumptions = models.JSONField(default=list)
    limitations = models.JSONField(default=list)
    actions = models.JSONField(default=list)
    # Calculated by the application, never by the model. Kept as they were when answered.
    facts = models.JSONField(default=list)
    used_fact_ids = models.JSONField(default=list)
    citations = models.JSONField(default=list)
    grounding_failed = models.BooleanField(default=False)
    is_synthetic = models.BooleanField(default=False)
    used_model = models.BooleanField(default=False)
    failure_code = models.CharField(max_length=40, blank=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantOwnedModel.Meta):
        indexes = [
            models.Index(fields=["tenant", "user", "-created_at"], name="assistant_recent_idx"),
        ]

    def __str__(self):
        return f"Întrebare {self.pk}"

    @property
    def used_facts(self):
        wanted = set(self.used_fact_ids)
        return [fact for fact in self.facts if fact["id"] in wanted]

    @property
    def is_pending(self):
        return self.status == self.Status.PENDING
