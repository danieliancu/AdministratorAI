from datetime import date

from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from apps.audit.services import record_tenant_event
from apps.core import filestore
from apps.core.db.scope import current_scope

from .models import Expense, ExpenseCategory, ExpenseDocument, RecurringExpense

MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
# The content decides the type, never the name or the header the browser sent.
_SIGNATURES = (
    (b"%PDF-", "application/pdf"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"\xff\xd8\xff", "image/jpeg"),
)


class DocumentRefused(Exception):
    pass


def category_named(name):
    name = (name or "").strip()
    if not name:
        return None
    existing = ExpenseCategory.objects.filter(name__iexact=name).first()
    return existing or ExpenseCategory.objects.create(
        tenant_id=current_scope().tenant_id, name=name
    )


def void_expense(expense_id, *, user_id):
    expense = Expense.objects.select_for_update(of=("self",)).get(pk=expense_id)
    if expense.voided_at is None:
        expense.voided_at = timezone.now()
        expense.save(update_fields=["voided_at"])
        record_tenant_event(
            "expense.voided",
            actor_user_id=user_id,
            metadata={"expense_id": str(expense.pk), "gross": str(expense.gross)},
        )
    return expense


def templates_due(month):
    """Active templates covering a month, given as its first day."""
    return RecurringExpense.objects.filter(
        Q(last_month__isnull=True) | Q(last_month__gte=month),
        is_active=True,
        first_month__lte=month,
    )


def missing_recurring(month):
    done = Expense.objects.filter(recurring_month=month).values("recurring_id")
    return templates_due(month).exclude(pk__in=done)


def generate_recurring(month, *, user_id):
    """Record a month's expenses from its templates. Running it twice adds nothing."""
    created = 0
    for template in missing_recurring(month):
        try:
            with transaction.atomic():
                Expense.objects.create(
                    tenant_id=template.tenant_id,
                    date=date(month.year, month.month, template.day_of_month),
                    supplier=template.supplier,
                    description=template.description,
                    category_id=template.category_id,
                    net=template.net,
                    vat=template.vat,
                    gross=template.gross,
                    recurring=template,
                    recurring_month=month,
                    created_by_id=user_id,
                )
        except IntegrityError:
            continue  # someone else generated it a moment ago
        created += 1
    if created:
        record_tenant_event(
            "expense.recurring_generated",
            actor_user_id=user_id,
            metadata={"month": month.isoformat(), "created": created},
        )
    return created


def detect_document_type(content):
    for signature, content_type in _SIGNATURES:
        if content.startswith(signature):
            return content_type
    return None


def attach_document(expense, *, name, content, user_id):
    if len(content) > MAX_DOCUMENT_BYTES:
        raise DocumentRefused("Fișierul depășește limita de 10 MB.")
    content_type = detect_document_type(content)
    if content_type is None:
        raise DocumentRefused("Sunt acceptate doar fișiere PDF, PNG sau JPEG.")
    key, checksum = filestore.put(expense.tenant_id, content)
    document, created = ExpenseDocument.objects.get_or_create(
        tenant_id=expense.tenant_id,
        expense=expense,
        sha256=checksum,
        defaults={
            "original_name": name[:255],
            "content_type": content_type,
            "size": len(content),
            "file_key": key,
            "uploaded_by_id": user_id,
        },
    )
    if created:
        record_tenant_event(
            "expense.document_added",
            actor_user_id=user_id,
            metadata={"expense_id": str(expense.pk), "document_id": str(document.pk)},
        )
    return document
