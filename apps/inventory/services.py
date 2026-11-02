from decimal import Decimal

from django.db.models import DecimalField, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from apps.audit.services import record_tenant_event
from apps.financial_imports.models import Source

from .models import Product, StockMovement

ZERO = Value(Decimal("0.000"), output_field=DecimalField(max_digits=14, decimal_places=3))


class StockError(Exception):
    """Carries a message written for the person using the page."""


def with_stock(queryset):
    """The stock level is always derived from the movements, so it cannot drift from them."""
    level = (
        StockMovement.objects.filter(product_id=OuterRef("pk"))
        .order_by()
        .values("product_id")
        .annotate(total=Sum("quantity"))
        .values("total")
    )
    return queryset.annotate(stock=Coalesce(Subquery(level), ZERO))


def low_stock():
    return (
        with_stock(Product.objects.filter(is_active=True, reorder_threshold__isnull=False))
        .filter(stock__lte=F("reorder_threshold"))
        .order_by("name")
    )


def signed_quantity(kind, quantity):
    """Receipts and issues are typed as positive; only an adjustment carries its own sign."""
    if kind == StockMovement.Kind.ADJUSTMENT:
        if quantity == 0:
            raise StockError("Ajustarea nu poate fi zero.")
        return quantity
    if quantity <= 0:
        raise StockError("Cantitatea trebuie să fie mai mare decât zero.")
    return quantity if kind == StockMovement.Kind.RECEIPT else -quantity


def level_of(product_id):
    total = StockMovement.objects.filter(product_id=product_id).aggregate(total=Sum("quantity"))
    return total["total"] or Decimal("0.000")


def record_movement(
    product_id,
    *,
    date,
    kind,
    quantity,
    reference="",
    user_id=None,
    source=Source.MANUAL,
    batch=None,
    fingerprint="",
):
    # The row lock makes concurrent issues see each other, so stock cannot go below zero.
    product = Product.objects.select_for_update(of=("self",)).get(pk=product_id)
    signed = signed_quantity(kind, quantity)
    level = level_of(product_id)
    if level + signed < 0:
        raise StockError(f"Stoc insuficient pentru {product.sku}: sunt disponibile {level}.")
    movement = StockMovement.objects.create(
        tenant_id=product.tenant_id,
        product=product,
        date=date,
        kind=kind,
        quantity=signed,
        reference=reference,
        source=source,
        import_batch=batch,
        import_fingerprint=fingerprint,
        created_by_id=user_id,
    )
    if source == Source.MANUAL:
        record_tenant_event(
            "stock.movement_recorded",
            actor_user_id=user_id,
            metadata={"product_id": str(product.pk), "kind": kind, "quantity": str(signed)},
        )
    return movement


def movements_between(start, end):
    return (
        StockMovement.objects.filter(date__range=(start, end))
        .order_by()
        .values("product_id")
        .annotate(
            received=Coalesce(Sum("quantity", filter=Q(kind="receipt")), ZERO),
            issued=Coalesce(Sum("quantity", filter=Q(kind="issue")), ZERO),
            adjusted=Coalesce(Sum("quantity", filter=Q(kind="adjustment")), ZERO),
        )
    )
