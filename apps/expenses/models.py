from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Lower
from django.utils import timezone

from apps.core.db.constraints import TenantFK
from apps.financial_imports.models import SourcedRecord, sourced_constraints
from apps.sales.models import MONEY, amounts_constraints
from apps.tenants.models import TenantOwnedModel


class ExpenseCategory(TenantOwnedModel):
    name = models.CharField("Denumire", max_length=100)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            models.UniqueConstraint("tenant", Lower("name"), name="expense_category_name_uniq"),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class RecurringExpense(TenantOwnedModel):
    """A template. It records nothing until someone generates the month's expenses."""

    description = models.CharField("Descriere", max_length=200)
    supplier = models.CharField("Furnizor", max_length=200)
    category = models.ForeignKey(
        ExpenseCategory,
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
    day_of_month = models.PositiveSmallIntegerField("Ziua din lună (1–28)", default=1)
    first_month = models.DateField("Prima zi a primei luni")
    last_month = models.DateField("Prima zi a ultimei luni", null=True, blank=True)
    is_active = models.BooleanField("Activă", default=True)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            *amounts_constraints("recurring"),
            TenantFK(
                column="category_id",
                to_table="expenses_expensecategory",
                name="recurring_category_tenant_fk",
            ),
            models.CheckConstraint(
                condition=Q(day_of_month__gte=1, day_of_month__lte=28), name="recurring_day_range"
            ),
            models.CheckConstraint(
                condition=Q(last_month__isnull=True) | Q(last_month__gte=F("first_month")),
                name="recurring_months_order",
            ),
        ]
        ordering = ["description"]

    def __str__(self):
        return self.description


class Expense(TenantOwnedModel, SourcedRecord):
    date = models.DateField("Data documentului")
    supplier = models.CharField("Furnizor", max_length=200)
    document_number = models.CharField("Număr document", max_length=60, blank=True)
    description = models.CharField("Descriere", max_length=200, blank=True)
    category = models.ForeignKey(
        ExpenseCategory,
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
    paid_date = models.DateField("Data plății", null=True, blank=True)
    recurring = models.ForeignKey(
        RecurringExpense,
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        db_constraint=False,
        related_name="expenses",
    )
    recurring_month = models.DateField(null=True, blank=True, editable=False)
    voided_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            *sourced_constraints("expense"),
            *amounts_constraints("expense"),
            TenantFK(
                column="category_id",
                to_table="expenses_expensecategory",
                name="expense_category_tenant_fk",
            ),
            TenantFK(
                column="recurring_id",
                to_table="expenses_recurringexpense",
                name="expense_recurring_tenant_fk",
            ),
            models.UniqueConstraint(
                fields=["tenant", "recurring", "recurring_month"],
                condition=Q(recurring__isnull=False),
                name="expense_one_per_recurring_month",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "date"], name="expense_date_idx"),
            models.Index(fields=["tenant", "paid_date"], name="expense_paid_idx"),
        ]
        ordering = ["-date", "-created_at"]

    def __str__(self):
        return f"{self.supplier} {self.document_number}".strip()


class ExpenseDocument(TenantOwnedModel):
    expense = models.ForeignKey(
        Expense, on_delete=models.DO_NOTHING, db_constraint=False, related_name="documents"
    )
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=50)
    size = models.PositiveIntegerField()
    file_key = models.CharField(max_length=200)
    sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta(TenantOwnedModel.Meta):
        constraints = [
            *TenantOwnedModel.Meta.constraints,
            TenantFK(
                column="expense_id", to_table="expenses_expense", name="document_expense_tenant_fk"
            ),
            models.UniqueConstraint(
                fields=["tenant", "expense", "sha256"], name="document_same_file_uniq"
            ),
        ]
        ordering = ["created_at"]

    def __str__(self):
        return self.original_name
