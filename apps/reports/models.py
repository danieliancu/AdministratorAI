from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.sales.models import MONEY
from apps.tenants.models import TenantOwnedModel


class OpeningCash(TenantOwnedModel):
    """Cash declared by the user at a date. Without it no cash position is shown."""

    amount = models.DecimalField("Sold de numerar și bancă", **MONEY)
    as_of = models.DateField("La data")
    declared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            models.UniqueConstraint(fields=["tenant"], name="opening_cash_one_per_tenant"),
        ]

    def __str__(self):
        return f"{self.amount} la {self.as_of}"
