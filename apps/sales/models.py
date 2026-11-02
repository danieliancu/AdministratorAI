from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower

from apps.core.db.constraints import TenantFK
from apps.financial_imports.models import SourcedRecord, sourced_constraints
from apps.tenants.models import TenantOwnedModel

MONEY = {"max_digits": 14, "decimal_places": 2}


def amounts_constraints(prefix):
    """Amounts come from the user and are checked, never calculated: VAT is not derived here."""
    return [
        models.CheckConstraint(
            condition=Q(gross__gt=0) & Q(net__gte=0) & Q(vat__gte=0),
            name=f"{prefix}_amounts_positive",
        ),
        models.CheckConstraint(
            condition=Q(gross=F("net") + F("vat")), name=f"{prefix}_gross_is_net_plus_vat"
        ),
    ]


class Customer(TenantOwnedModel, SourcedRecord):
    name = models.CharField("Denumire", max_length=200)
    cui = models.CharField("CUI", max_length=20, blank=True)
    email = models.EmailField("Email", blank=True)
    phone = models.CharField("Telefon", max_length=40, blank=True)
    is_active = models.BooleanField("Activ", default=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            *sourced_constraints("customer"),
            models.UniqueConstraint(
                fields=["tenant", "cui"], condition=~Q(cui=""), name="customer_cui_uniq"
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class SalesCategory(TenantOwnedModel):
    name = models.CharField("Denumire", max_length=100)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            models.UniqueConstraint("tenant", Lower("name"), name="sales_category_name_uniq"),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Invoice(TenantOwnedModel, SourcedRecord):
    class Status(models.TextChoices):
        ISSUED = "issued", "Emisă"
        CANCELLED = "cancelled", "Anulată"

    number = models.CharField("Număr", max_length=60)
    customer = models.ForeignKey(
        Customer,
        verbose_name="Client",
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="invoices",
    )
    category = models.ForeignKey(
        SalesCategory,
        verbose_name="Categorie",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    issue_date = models.DateField("Data emiterii")
    due_date = models.DateField("Scadența", null=True, blank=True)
    net = models.DecimalField("Valoare fără TVA", **MONEY)
    vat = models.DecimalField("TVA", **MONEY)
    gross = models.DecimalField("Total", **MONEY)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ISSUED)
    notes = models.CharField("Observații", max_length=500, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            *sourced_constraints("invoice"),
            *amounts_constraints("invoice"),
            TenantFK(
                column="customer_id", to_table="sales_customer", name="invoice_customer_tenant_fk"
            ),
            TenantFK(
                column="category_id",
                to_table="sales_salescategory",
                name="invoice_category_tenant_fk",
            ),
            # A cancelled invoice keeps its number: numbering stays traceable.
            models.UniqueConstraint(fields=["tenant", "number"], name="invoice_number_uniq"),
            models.CheckConstraint(
                condition=Q(due_date__isnull=True) | Q(due_date__gte=F("issue_date")),
                name="invoice_due_after_issue",
            ),
        ]
        indexes = [models.Index(fields=["tenant", "issue_date"], name="invoice_issue_idx")]
        ordering = ["-issue_date", "-number"]

    def __str__(self):
        return self.number


class Payment(TenantOwnedModel, SourcedRecord):
    """Cash received. Kept apart from the invoice: issuing is not collecting."""

    class Method(models.TextChoices):
        BANK = "bank", "Transfer bancar"
        CASH = "cash", "Numerar"
        CARD = "card", "Card"
        OTHER = "other", "Altă metodă"

    invoice = models.ForeignKey(
        Invoice, on_delete=models.DO_NOTHING, db_constraint=False, related_name="payments"
    )
    date = models.DateField("Data încasării")
    amount = models.DecimalField("Sumă încasată", **MONEY)
    method = models.CharField("Metodă", max_length=10, choices=Method.choices, default=Method.BANK)
    reference = models.CharField("Referință", max_length=100, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            *sourced_constraints("payment"),
            TenantFK(
                column="invoice_id", to_table="sales_invoice", name="payment_invoice_tenant_fk"
            ),
            models.CheckConstraint(condition=Q(amount__gt=0), name="payment_amount_positive"),
        ]
        indexes = [models.Index(fields=["tenant", "date"], name="payment_date_idx")]
        ordering = ["date", "created_at"]

    def __str__(self):
        return f"{self.invoice_id} / {self.amount}"


class SaleTransaction(TenantOwnedModel, SourcedRecord):
    """A sale without an invoice in this system, such as a daily POS total: paid on the spot."""

    date = models.DateField("Data")
    description = models.CharField("Descriere", max_length=200)
    customer = models.ForeignKey(
        Customer,
        verbose_name="Client",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    category = models.ForeignKey(
        SalesCategory,
        verbose_name="Categorie",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="+",
    )
    net = models.DecimalField("Valoare fără TVA", **MONEY)
    vat = models.DecimalField("TVA", **MONEY)
    gross = models.DecimalField("Total", **MONEY)
    reference = models.CharField("Referință", max_length=100, blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            *sourced_constraints("sale"),
            *amounts_constraints("sale"),
            TenantFK(
                column="customer_id", to_table="sales_customer", name="sale_customer_tenant_fk"
            ),
            TenantFK(
                column="category_id", to_table="sales_salescategory", name="sale_category_tenant_fk"
            ),
        ]
        indexes = [models.Index(fields=["tenant", "date"], name="sale_date_idx")]
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return self.description
