from django.contrib import messages
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.audit.services import record_tenant_event
from apps.core.listing import is_htmx, page_of
from apps.tenants import roles
from apps.tenants.roles import requires

from . import services
from .forms import CustomerForm, InvoiceForm, PaymentForm, SaleForm
from .models import Customer, Invoice, Payment, SalesCategory, SaleTransaction

SECTION = "invoice-list"


def _categories():
    return SalesCategory.objects.values_list("name", flat=True)


def _listing(request, template, partial, context):
    return render(request, partial if is_htmx(request) else template, context)


def _can_edit(request):
    return request.tenant_access.can(roles.EDIT_FINANCE)


def _form_page(request, form, title, submit="Salvează", note=None, categories=True):
    return render(
        request,
        "components/form_page.html",
        {
            "form": form,
            "title": title,
            "submit": submit,
            "note": note,
            "categories": _categories() if categories else None,
            "active_section": SECTION,
        },
    )


def _save_unique(form, field, message):
    """Two people can pass the form's check at once; the constraint decides, on a savepoint."""
    try:
        with transaction.atomic():
            return form.save()
    except IntegrityError:
        form.add_error(field, message)
        return None


@requires(roles.VIEW_FINANCE)
def invoice_list(request, tenant_id):
    search = request.GET.get("q", "").strip()
    state = request.GET.get("stare", "")
    invoices = services.with_paid(Invoice.objects.select_related("customer"))
    if search:
        invoices = invoices.filter(
            Q(number__icontains=search) | Q(customer__name__icontains=search)
        )
    if state in Invoice.Status.values:
        invoices = invoices.filter(status=state)
    return _listing(
        request,
        "sales/invoice_list.html",
        "sales/_invoice_table.html",
        {
            "page": page_of(request, invoices),
            "search": search,
            "state": state,
            "can_edit": _can_edit(request),
        },
    )


@requires(roles.EDIT_FINANCE)
def invoice_new(request, tenant_id):
    form = InvoiceForm(
        request.POST or None,
        tenant_id=tenant_id,
        initial={"issue_date": timezone.localdate(), "vat": "0"},
    )
    form.instance.created_by_id = request.user.pk
    if request.method == "POST" and form.is_valid():
        invoice = _save_unique(form, "number", "Există deja o factură cu acest număr.")
        if invoice:
            record_tenant_event(
                "invoice.created",
                actor_user_id=request.user.pk,
                metadata={"invoice_id": str(invoice.pk), "number": invoice.number},
            )
            messages.success(request, f"Factura {invoice.number} a fost înregistrată.")
            return redirect("tenant:invoice-detail", tenant_id=tenant_id, pk=invoice.pk)
    return _form_page(
        request,
        form,
        "Factură nouă",
        "Salvează factura",
        "Sumele sunt cele de pe factură. Aplicația nu calculează TVA.",
    )


@requires(roles.VIEW_FINANCE)
def invoice_detail(request, tenant_id, pk):
    invoice = get_object_or_404(
        services.with_paid(Invoice.objects.select_related("customer", "category")), pk=pk
    )
    form = PaymentForm(
        request.POST or None,
        initial={"date": timezone.localdate(), "amount": invoice.gross - invoice.paid},
    )
    if request.method == "POST":
        if not _can_edit(request):
            raise Http404
        if form.is_valid():
            try:
                services.record_payment(invoice.pk, user_id=request.user.pk, **form.cleaned_data)
            except services.SalesError as exc:
                form.add_error("amount", str(exc))
            else:
                messages.success(request, "Încasarea a fost înregistrată.")
                return redirect("tenant:invoice-detail", tenant_id=tenant_id, pk=pk)
    return render(
        request,
        "sales/invoice_detail.html",
        {
            "invoice": invoice,
            "remaining": invoice.gross - invoice.paid,
            "payments": Payment.objects.filter(invoice=invoice),
            "form": form,
            "can_edit": _can_edit(request),
            "is_issued": invoice.status == Invoice.Status.ISSUED,
            "active_section": SECTION,
        },
    )


@requires(roles.EDIT_FINANCE)
def invoice_edit(request, tenant_id, pk):
    invoice = get_object_or_404(services.with_paid(Invoice.objects.all()), pk=pk)
    if invoice.status != Invoice.Status.ISSUED:
        messages.error(request, "O factură anulată nu mai poate fi modificată.")
        return redirect("tenant:invoice-detail", tenant_id=tenant_id, pk=pk)
    form = InvoiceForm(
        request.POST or None, instance=invoice, tenant_id=tenant_id, paid=invoice.paid
    )
    if request.method == "POST" and form.is_valid():
        saved = _save_unique(form, "number", "Există deja o factură cu acest număr.")
        if saved:
            record_tenant_event(
                "invoice.updated",
                actor_user_id=request.user.pk,
                metadata={"invoice_id": str(pk), "changes": form.changes()},
            )
            messages.success(request, "Factura a fost actualizată.")
            return redirect("tenant:invoice-detail", tenant_id=tenant_id, pk=pk)
    return _form_page(request, form, f"Editează factura {invoice.number}")


@require_POST
@requires(roles.EDIT_FINANCE)
def invoice_cancel(request, tenant_id, pk):
    get_object_or_404(Invoice, pk=pk)
    try:
        services.cancel_invoice(pk, user_id=request.user.pk)
    except services.SalesError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Factura a fost anulată.")
    return redirect("tenant:invoice-detail", tenant_id=tenant_id, pk=pk)


@require_POST
@requires(roles.EDIT_FINANCE)
def payment_void(request, tenant_id, pk):
    payment = get_object_or_404(Payment, pk=pk)
    services.void_payment(pk, user_id=request.user.pk)
    messages.success(request, "Încasarea a fost anulată.")
    return redirect("tenant:invoice-detail", tenant_id=tenant_id, pk=payment.invoice_id)


@requires(roles.VIEW_FINANCE)
def sale_list(request, tenant_id):
    search = request.GET.get("q", "").strip()
    sales = SaleTransaction.objects.select_related("customer", "category")
    if search:
        sales = sales.filter(Q(description__icontains=search) | Q(reference__icontains=search))
    return _listing(
        request,
        "sales/sale_list.html",
        "sales/_sale_table.html",
        {
            "page": page_of(request, sales),
            "search": search,
            "can_edit": _can_edit(request),
            "active_section": SECTION,
        },
    )


@requires(roles.EDIT_FINANCE)
def sale_new(request, tenant_id):
    form = SaleForm(
        request.POST or None,
        tenant_id=tenant_id,
        initial={"date": timezone.localdate(), "vat": "0"},
    )
    form.instance.created_by_id = request.user.pk
    if request.method == "POST" and form.is_valid():
        sale = form.save()
        record_tenant_event(
            "sale.created",
            actor_user_id=request.user.pk,
            metadata={"sale_id": str(sale.pk), "gross": str(sale.gross)},
        )
        messages.success(request, "Vânzarea a fost înregistrată.")
        return redirect("tenant:sale-list", tenant_id=tenant_id)
    return _form_page(
        request,
        form,
        "Vânzare fără factură",
        "Salvează vânzarea",
        "De exemplu totalul zilnic de pe casa de marcat. Se consideră încasată la data vânzării.",
    )


@requires(roles.EDIT_FINANCE)
def sale_edit(request, tenant_id, pk):
    sale = get_object_or_404(SaleTransaction, pk=pk, voided_at__isnull=True)
    form = SaleForm(request.POST or None, instance=sale, tenant_id=tenant_id)
    if request.method == "POST" and form.is_valid():
        form.save()
        record_tenant_event(
            "sale.updated",
            actor_user_id=request.user.pk,
            metadata={"sale_id": str(pk), "changes": form.changes()},
        )
        messages.success(request, "Vânzarea a fost actualizată.")
        return redirect("tenant:sale-list", tenant_id=tenant_id)
    return _form_page(request, form, "Editează vânzarea")


@require_POST
@requires(roles.EDIT_FINANCE)
def sale_void(request, tenant_id, pk):
    get_object_or_404(SaleTransaction, pk=pk)
    services.void_sale(pk, user_id=request.user.pk)
    messages.success(request, "Vânzarea a fost anulată.")
    return redirect("tenant:sale-list", tenant_id=tenant_id)


@requires(roles.VIEW_FINANCE)
def customer_list(request, tenant_id):
    search = request.GET.get("q", "").strip()
    customers = Customer.objects.all()
    if search:
        customers = customers.filter(Q(name__icontains=search) | Q(cui__icontains=search))
    return _listing(
        request,
        "sales/customer_list.html",
        "sales/_customer_table.html",
        {
            "page": page_of(request, customers),
            "search": search,
            "can_edit": _can_edit(request),
            "active_section": SECTION,
        },
    )


def _save_customer(request, form):
    customer = _save_unique(form, "cui", "Există deja un client cu acest CUI.")
    if customer:
        record_tenant_event(
            "customer.saved",
            actor_user_id=request.user.pk,
            metadata={"customer_id": str(customer.pk)},
        )
    return customer


@requires(roles.EDIT_FINANCE)
def customer_new(request, tenant_id):
    form = CustomerForm(request.POST or None, tenant_id=tenant_id)
    form.instance.created_by_id = request.user.pk
    if request.method == "POST" and form.is_valid() and _save_customer(request, form):
        messages.success(request, "Clientul a fost adăugat.")
        return redirect("tenant:customer-list", tenant_id=tenant_id)
    return _form_page(request, form, "Client nou", categories=False)


@requires(roles.EDIT_FINANCE)
def customer_edit(request, tenant_id, pk):
    customer = get_object_or_404(Customer, pk=pk)
    form = CustomerForm(request.POST or None, instance=customer, tenant_id=tenant_id)
    if request.method == "POST" and form.is_valid() and _save_customer(request, form):
        messages.success(request, "Clientul a fost actualizat.")
        return redirect("tenant:customer-list", tenant_id=tenant_id)
    return _form_page(request, form, f"Editează {customer.name}", categories=False)
