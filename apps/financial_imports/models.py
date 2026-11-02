from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from apps.core.db.constraints import TenantFK
from apps.tenants.models import TenantOwnedModel


class Source(models.TextChoices):
    MANUAL = "manual", "Introdus manual"
    IMPORT = "import", "Importat"


class SourcedRecord(models.Model):
    """Where a financial record came from. The subclass adds the matching constraints."""

    source = models.CharField(max_length=10, choices=Source.choices, default=Source.MANUAL)
    import_batch = models.ForeignKey(
        "financial_imports.ImportBatch",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    import_fingerprint = models.CharField(max_length=64, blank=True, editable=False)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        abstract = True


def sourced_constraints(prefix):
    return [
        TenantFK(
            column="import_batch_id",
            to_table="financial_imports_importbatch",
            name=f"{prefix}_import_batch_tenant_fk",
        ),
        # The same imported row cannot produce a second record, even across files.
        models.UniqueConstraint(
            fields=["tenant", "import_fingerprint"],
            condition=~Q(import_fingerprint=""),
            name=f"{prefix}_fingerprint_uniq",
        ),
    ]


class ImportBatch(TenantOwnedModel):
    class Kind(models.TextChoices):
        CUSTOMERS = "customers", "Clienți"
        INVOICES = "invoices", "Facturi"
        PAYMENTS = "payments", "Încasări"
        SALES = "sales", "Vânzări fără factură"
        EXPENSES = "expenses", "Cheltuieli"
        PRODUCTS = "products", "Produse"
        MOVEMENTS = "movements", "Mișcări de stoc"

    class Status(models.TextChoices):
        PREVIEW = "preview", "De verificat"
        COMMITTED = "committed", "Importat"
        DISCARDED = "discarded", "Renunțat"

    kind = models.CharField(max_length=20, choices=Kind.choices)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PREVIEW)
    original_name = models.CharField(max_length=255)
    file_key = models.CharField(max_length=200)
    sha256 = models.CharField(max_length=64)
    size = models.PositiveIntegerField()
    headers = models.JSONField(default=list)
    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    invalid_rows = models.PositiveIntegerField(default=0)
    duplicate_rows = models.PositiveIntegerField(default=0)
    imported_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            # Uploading the same file twice returns the first batch.
            models.UniqueConstraint(
                fields=["tenant", "kind", "sha256"],
                condition=~Q(status="discarded"),
                name="import_batch_same_file_uniq",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "-created_at"], name="import_batch_recent_idx")]

    def __str__(self):
        return self.original_name


class ImportRow(TenantOwnedModel):
    class Status(models.TextChoices):
        VALID = "valid", "Valid"
        INVALID = "invalid", "Cu erori"
        DUPLICATE = "duplicate", "Duplicat"
        IMPORTED = "imported", "Importat"
        FAILED = "failed", "Eșuat la import"

    batch = models.ForeignKey(
        ImportBatch, on_delete=models.DO_NOTHING, db_constraint=False, related_name="rows"
    )
    number = models.PositiveIntegerField()
    # The original cells. The application role cannot change this column.
    raw = models.JSONField()
    status = models.CharField(max_length=20, choices=Status.choices)
    errors = models.JSONField(default=list)
    target_id = models.UUIDField(null=True, blank=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            TenantFK(
                column="batch_id",
                to_table="financial_imports_importbatch",
                name="import_row_batch_tenant_fk",
            ),
            models.UniqueConstraint(
                fields=["tenant", "batch", "number"], name="import_row_number_uniq"
            ),
        ]
        ordering = ["number"]

    def __str__(self):
        return f"Rând {self.number}"
