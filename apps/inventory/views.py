from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render

from apps.audit.services import record_tenant_event
from apps.core.listing import is_htmx, page_of
from apps.tenants import roles
from apps.tenants.roles import requires

from . import services
from .forms import MovementForm, ProductForm
from .models import Product, StockMovement


def _can_edit(request):
    return request.tenant_access.can(roles.EDIT_FINANCE)


@requires(roles.VIEW_FINANCE)
def product_list(request, tenant_id):
    search = request.GET.get("q", "").strip()
    only_low = request.GET.get("filtru") == "stoc-redus"
    products = services.with_stock(Product.objects.all()).order_by("name")
    if search:
        products = products.filter(Q(sku__icontains=search) | Q(name__icontains=search))
    if only_low:
        products = products.filter(
            is_active=True, reorder_threshold__isnull=False, stock__lte=F("reorder_threshold")
        )
    context = {
        "page": page_of(request, products),
        "search": search,
        "only_low": only_low,
        "can_edit": _can_edit(request),
    }
    template = (
        "inventory/_product_table.html" if is_htmx(request) else "inventory/product_list.html"
    )
    return render(request, template, context)


def _save(request, form, tenant_id, message):
    try:
        with transaction.atomic():
            product = form.save()
    except IntegrityError:
        form.add_error("sku", "Există deja un produs cu acest cod.")
        return None
    record_tenant_event(
        "product.saved",
        actor_user_id=request.user.pk,
        metadata={"product_id": str(product.pk), "changes": form.changes()},
    )
    messages.success(request, message)
    return redirect("tenant:product-detail", tenant_id=tenant_id, pk=product.pk)


def _form_page(request, form, title):
    return render(
        request,
        "components/form_page.html",
        {
            "form": form,
            "title": title,
            "submit": "Salvează",
            "note": "Costul este cel declarat de tine. Valoarea calculată cu el este o estimare.",
            "active_section": "product-list",
        },
    )


@requires(roles.EDIT_FINANCE)
def product_new(request, tenant_id):
    form = ProductForm(request.POST or None, tenant_id=tenant_id)
    form.instance.created_by_id = request.user.pk
    if request.method == "POST" and form.is_valid():
        response = _save(request, form, tenant_id, "Produsul a fost adăugat.")
        if response:
            return response
    return _form_page(request, form, "Produs nou")


@requires(roles.EDIT_FINANCE)
def product_edit(request, tenant_id, pk):
    product = get_object_or_404(Product, pk=pk)
    form = ProductForm(request.POST or None, instance=product, tenant_id=tenant_id)
    if request.method == "POST" and form.is_valid():
        response = _save(request, form, tenant_id, "Produsul a fost actualizat.")
        if response:
            return response
    return _form_page(request, form, f"Editează {product.name}")


@requires(roles.VIEW_FINANCE)
def product_detail(request, tenant_id, pk):
    product = get_object_or_404(services.with_stock(Product.objects.all()), pk=pk)
    form = MovementForm(request.POST or None)
    if request.method == "POST":
        if not _can_edit(request):
            raise Http404
        if form.is_valid():
            try:
                services.record_movement(pk, user_id=request.user.pk, **form.cleaned_data)
            except services.StockError as exc:
                form.add_error("quantity", str(exc))
            else:
                messages.success(request, "Mișcarea a fost înregistrată.")
                return redirect("tenant:product-detail", tenant_id=tenant_id, pk=pk)
    return render(
        request,
        "inventory/product_detail.html",
        {
            "product": product,
            "page": page_of(request, StockMovement.objects.filter(product=product)),
            "form": form,
            "is_low": (
                product.reorder_threshold is not None and product.stock <= product.reorder_threshold
            ),
            "can_edit": _can_edit(request),
            "active_section": "product-list",
        },
    )
