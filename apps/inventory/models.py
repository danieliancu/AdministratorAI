from django.db import models
from django.db.models import Q

from apps.core.db.constraints import TenantFK
from apps.financial_imports.models import SourcedRecord, sourced_constraints
from apps.sales.models import MONEY
from apps.tenants.models import TenantOwnedModel

QUANTITY = {"max_digits": 14, "decimal_places": 3}


class Product(TenantOwnedModel, SourcedRecord):
    sku = models.CharField("Cod", max_length=60)
    name = models.CharField("Denumire", max_length=200)
    unit = models.CharField("Unitate de măsură", max_length=20, default="buc")
    reorder_threshold = models.DecimalField(
        "Prag de reaprovizionare", null=True, blank=True, **QUANTITY
    )
    unit_cost = models.DecimalField("Cost unitar declarat", null=True, blank=True, **MONEY)
    is_active = models.BooleanField("Activ", default=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            *sourced_constraints("product"),
            models.UniqueConstraint(fields=["tenant", "sku"], name="product_sku_uniq"),
            models.CheckConstraint(
                condition=Q(reorder_threshold__isnull=True) | Q(reorder_threshold__gte=0),
                name="product_threshold_not_negative",
            ),
            models.CheckConstraint(
                condition=Q(unit_cost__isnull=True) | Q(unit_cost__gte=0),
                name="product_cost_not_negative",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return f"{self.sku} · {self.name}"


class StockMovement(TenantOwnedModel, SourcedRecord):
    """Append-only: the stock level is the sum of these, and a correction is a new row."""

    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Intrare"
        ISSUE = "issue", "Ieșire"
        ADJUSTMENT = "adjustment", "Ajustare"

    product = models.ForeignKey(
        Product, on_delete=models.DO_NOTHING, db_constraint=False, related_name="movements"
    )
    date = models.DateField("Data")
    kind = models.CharField("Tip", max_length=12, choices=Kind.choices)
    quantity = models.DecimalField("Cantitate", **QUANTITY)
    reference = models.CharField("Referință", max_length=100, blank=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            *sourced_constraints("movement"),
            TenantFK(
                column="product_id", to_table="inventory_product", name="movement_product_tenant_fk"
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind="receipt", quantity__gt=0)
                    | Q(kind="issue", quantity__lt=0)
                    | (Q(kind="adjustment") & ~Q(quantity=0))
                ),
                name="movement_sign_matches_kind",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "product", "date"], name="movement_product_idx")]
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.product_id} {self.quantity}"
