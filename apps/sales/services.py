from decimal import Decimal

from django.db.models import DecimalField, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.audit.services import record_tenant_event
from apps.core.db.scope import current_scope
from apps.financial_imports.models import Source

from .models import Customer, Invoice, Payment, SalesCategory, SaleTransaction

ZERO = Value(Decimal("0.00"), output_field=DecimalField(max_digits=14, decimal_places=2))


class SalesError(Exception):
    """Carries a message written for the person using the page."""


def with_paid(queryset, as_of=None):
    """Annotate the amount collected. A subquery: joining payments would multiply the totals."""
    payments = Payment.objects.filter(invoice_id=OuterRef("pk"), voided_at__isnull=True)
    if as_of is not None:
        payments = payments.filter(date__lte=as_of)
    paid = payments.order_by().values("invoice_id").annotate(total=Sum("amount")).values("total")
    return queryset.annotate(paid=Coalesce(Subquery(paid), ZERO))


def category_named(name):
    name = (name or "").strip()
    if not name:
        return None
    existing = SalesCategory.objects.filter(name__iexact=name).first()
    return existing or SalesCategory.objects.create(tenant_id=current_scope().tenant_id, name=name)


def _locked_invoice(invoice_id):
    return Invoice.objects.select_for_update(of=("self",)).get(pk=invoice_id)


def _paid_so_far(invoice_id):
    total = Payment.objects.filter(invoice_id=invoice_id, voided_at__isnull=True).aggregate(
        total=Sum("amount")
    )["total"]
    return total or Decimal("0.00")


def record_payment(
    invoice_id,
    *,
    date,
    amount,
    method=Payment.Method.BANK,
    reference="",
    user_id=None,
    source=Source.MANUAL,
    batch=None,
    fingerprint="",
):
    # The row lock makes concurrent payments see each other, so neither can overpay.
    invoice = _locked_invoice(invoice_id)
    if invoice.status != Invoice.Status.ISSUED:
        raise SalesError("Factura este anulată și nu poate primi încasări.")
    remaining = invoice.gross - _paid_so_far(invoice_id)
    if amount > remaining:
        raise SalesError(f"Suma depășește restul de încasat ({remaining} lei).")
    payment = Payment.objects.create(
        tenant_id=invoice.tenant_id,
        invoice=invoice,
        date=date,
        amount=amount,
        method=method,
        reference=reference,
        source=source,
        import_batch=batch,
        import_fingerprint=fingerprint,
        created_by_id=user_id,
    )
    if source == Source.MANUAL:
        record_tenant_event(
            "payment.recorded",
            actor_user_id=user_id,
            metadata={"invoice_id": str(invoice.pk), "amount": str(amount)},
        )
    return payment


def void_payment(payment_id, *, user_id):
    payment = Payment.objects.select_for_update(of=("self",)).get(pk=payment_id)
    if payment.voided_at is None:
        payment.voided_at = timezone.now()
        payment.voided_by_id = user_id
        payment.save(update_fields=["voided_at", "voided_by"])
        record_tenant_event(
            "payment.voided",
            actor_user_id=user_id,
            metadata={"payment_id": str(payment.pk), "amount": str(payment.amount)},
        )
    return payment


def cancel_invoice(invoice_id, *, user_id):
    invoice = _locked_invoice(invoice_id)
    if invoice.status == Invoice.Status.CANCELLED:
        return invoice
    if _paid_so_far(invoice_id) > 0:
        raise SalesError("Factura are încasări active. Anulează mai întâi încasările.")
    invoice.status = Invoice.Status.CANCELLED
    invoice.cancelled_at = timezone.now()
    invoice.save(update_fields=["status", "cancelled_at"])
    record_tenant_event(
        "invoice.cancelled",
        actor_user_id=user_id,
        metadata={"invoice_id": str(invoice.pk), "number": invoice.number},
    )
    return invoice


def void_sale(sale_id, *, user_id):
    sale = SaleTransaction.objects.select_for_update(of=("self",)).get(pk=sale_id)
    if sale.voided_at is None:
        sale.voided_at = timezone.now()
        sale.save(update_fields=["voided_at"])
        record_tenant_event(
            "sale.voided",
            actor_user_id=user_id,
            metadata={"sale_id": str(sale.pk), "gross": str(sale.gross)},
        )
    return sale


def find_or_create_customer(name, cui="", *, user_id=None, source=Source.MANUAL, batch=None):
    name, cui = name.strip(), (cui or "").strip()
    customer = None
    if cui:
        customer = Customer.objects.filter(cui=cui).first()
    if customer is None:
        customer = Customer.objects.filter(name__iexact=name, cui__in=["", cui]).first()
    if customer is not None:
        return customer
    return Customer.objects.create(
        tenant_id=current_scope().tenant_id,
        name=name,
        cui=cui,
        source=source,
        import_batch=batch,
        created_by_id=user_id,
    )
