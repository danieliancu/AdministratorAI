import uuid

from django.db import models
from django.utils import timezone


class AuditEvent(models.Model):
    """Append-only, enforced in the database. No foreign keys, so events outlive what they name."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # The database stamps both values on insert, so the application cannot backdate an event.
    occurred_at = models.DateTimeField(default=timezone.now, editable=False)
    db_role = models.CharField(max_length=63, blank=True, editable=False)
    actor_user_id = models.UUIDField(null=True, blank=True)
    action = models.CharField(max_length=80)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.action} {self.pk}"


class TenantEvent(AuditEvent):
    tenant_id = models.UUIDField()

    class Meta:
        indexes = [models.Index(fields=["tenant_id", "occurred_at"], name="tenantevent_tenant_idx")]


class SecurityEvent(AuditEvent):
    identifier_hash = models.CharField(max_length=64, blank=True)
    ip_address = models.CharField(max_length=45, blank=True)


class PlatformEvent(AuditEvent):
    target_tenant_id = models.UUIDField(null=True, blank=True)
    reason = models.TextField(blank=True)
