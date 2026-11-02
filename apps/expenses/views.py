from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_POST

from apps.audit.services import record_tenant_event
from apps.core import filestore
from apps.core.listing import is_htmx, page_of
from apps.tenants import roles
from apps.tenants.roles import requires

from . import services
from .forms import DocumentForm, ExpenseForm, RecurringForm
from .models import Expense, ExpenseCategory, ExpenseDocument, RecurringExpense

SECTION = "expense-list"


def _can_edit(request):
    return request.tenant_access.can(roles.EDIT_FINANCE)


def _current_month():
    return timezone.localdate().replace(day=1)


def _form_page(request, form, title, submit="Salvează", note=None):
    return render(
        request,
        "components/form_page.html",
        {
            "form": form,
            "title": title,
            "submit": submit,
            "note": note,
            "categories": ExpenseCategory.objects.values_list("name", flat=True),
            "active_section": SECTION,
        },
    )


@requires(roles.VIEW_FINANCE)
def expense_list(request, tenant_id):
    search = request.GET.get("q", "").strip()
    state = request.GET.get("stare", "")
    expenses = Expense.objects.select_related("category")
    if search:
        expenses = expenses.filter(
            Q(supplier__icontains=search)
            | Q(document_number__icontains=search)
            | Q(description__icontains=search)
        )
    if state == "neplatite":
        expenses = expenses.filter(paid_date__isnull=True, voided_at__isnull=True)
    elif state == "platite":
        expenses = expenses.filter(paid_date__isnull=False, voided_at__isnull=True)
    context = {
        "page": page_of(request, expenses),
        "search": search,
        "state": state,
        "can_edit": _can_edit(request),
    }
    template = "expenses/_expense_table.html" if is_htmx(request) else "expenses/expense_list.html"
    return render(request, template, context)


@requires(roles.EDIT_FINANCE)
def expense_new(request, tenant_id):
    form = ExpenseForm(
        request.POST or None,
        tenant_id=tenant_id,
        initial={"date": timezone.localdate(), "vat": "0"},
    )
    form.instance.created_by_id = request.user.pk
    if request.method == "POST" and form.is_valid():
        expense = form.save()
        record_tenant_event(
            "expense.created",
            actor_user_id=request.user.pk,
            metadata={"expense_id": str(expense.pk), "gross": str(expense.gross)},
        )
        messages.success(request, "Cheltuiala a fost înregistrată.")
        return redirect("tenant:expense-detail", tenant_id=tenant_id, pk=expense.pk)
    return _form_page(
        request,
        form,
        "Cheltuială nouă",
        "Salvează cheltuiala",
        "Sumele sunt cele de pe document. Aplicația nu calculează TVA.",
    )


@requires(roles.VIEW_FINANCE)
def expense_detail(request, tenant_id, pk):
    expense = get_object_or_404(Expense.objects.select_related("category"), pk=pk)
    form = DocumentForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if not _can_edit(request):
            raise Http404
        if form.is_valid():
            upload = form.cleaned_data["file"]
            try:
                if upload.size > services.MAX_DOCUMENT_BYTES:
                    raise services.DocumentRefused("Fișierul depășește limita de 10 MB.")
                services.attach_document(
                    expense, name=upload.name, content=upload.read(), user_id=request.user.pk
                )
            except services.DocumentRefused as exc:
                form.add_error("file", str(exc))
            else:
                messages.success(request, "Documentul a fost atașat.")
                return redirect("tenant:expense-detail", tenant_id=tenant_id, pk=pk)
    return render(
        request,
        "expenses/expense_detail.html",
        {
            "expense": expense,
            "documents": ExpenseDocument.objects.filter(expense=expense),
            "form": form,
            "can_edit": _can_edit(request),
            "active_section": SECTION,
        },
    )


@requires(roles.EDIT_FINANCE)
def expense_edit(request, tenant_id, pk):
    expense = get_object_or_404(Expense, pk=pk, voided_at__isnull=True)
    form = ExpenseForm(request.POST or None, instance=expense, tenant_id=tenant_id)
    if request.method == "POST" and form.is_valid():
        form.save()
        record_tenant_event(
            "expense.updated",
            actor_user_id=request.user.pk,
            metadata={"expense_id": str(pk), "changes": form.changes()},
        )
        messages.success(request, "Cheltuiala a fost actualizată.")
        return redirect("tenant:expense-detail", tenant_id=tenant_id, pk=pk)
    return _form_page(request, form, "Editează cheltuiala")


@require_POST
@requires(roles.EDIT_FINANCE)
def expense_void(request, tenant_id, pk):
    get_object_or_404(Expense, pk=pk)
    services.void_expense(pk, user_id=request.user.pk)
    messages.success(request, "Cheltuiala a fost anulată.")
    return redirect("tenant:expense-detail", tenant_id=tenant_id, pk=pk)


@requires(roles.VIEW_FINANCE)
def document_download(request, tenant_id, pk):
    document = get_object_or_404(ExpenseDocument, pk=pk)
    content = filestore.get(tenant_id, document.file_key)
    response = HttpResponse(content, content_type=document.content_type)
    # Always a download: an uploaded file must never run in the application's origin.
    response["Content-Disposition"] = content_disposition_header(True, document.original_name)
    response["X-Content-Type-Options"] = "nosniff"
    return response


@requires(roles.VIEW_FINANCE)
def recurring_list(request, tenant_id):
    month = _current_month()
    return render(
        request,
        "expenses/recurring_list.html",
        {
            "templates": RecurringExpense.objects.select_related("category"),
            "missing": services.missing_recurring(month).count(),
            "can_edit": _can_edit(request),
            "active_section": SECTION,
        },
    )


RECURRING_NOTE = "Un șablon nu înregistrează nimic singur: cheltuielile apar când le generezi."


@requires(roles.EDIT_FINANCE)
def recurring_new(request, tenant_id):
    form = RecurringForm(
        request.POST or None,
        tenant_id=tenant_id,
        initial={"first_month": _current_month(), "vat": "0"},
    )
    if request.method == "POST" and form.is_valid():
        template = form.save()
        record_tenant_event(
            "expense.recurring_saved",
            actor_user_id=request.user.pk,
            metadata={"template_id": str(template.pk)},
        )
        messages.success(request, "Șablonul a fost salvat.")
        return redirect("tenant:recurring-list", tenant_id=tenant_id)
    return _form_page(request, form, "Cheltuială recurentă nouă", note=RECURRING_NOTE)


@requires(roles.EDIT_FINANCE)
def recurring_edit(request, tenant_id, pk):
    template = get_object_or_404(RecurringExpense, pk=pk)
    form = RecurringForm(request.POST or None, instance=template, tenant_id=tenant_id)
    if request.method == "POST" and form.is_valid():
        form.save()
        record_tenant_event(
            "expense.recurring_saved",
            actor_user_id=request.user.pk,
            metadata={"template_id": str(pk), "changes": form.changes()},
        )
        messages.success(request, "Șablonul a fost actualizat.")
        return redirect("tenant:recurring-list", tenant_id=tenant_id)
    return _form_page(request, form, "Editează șablonul", note=RECURRING_NOTE)


@require_POST
@requires(roles.EDIT_FINANCE)
def recurring_generate(request, tenant_id):
    created = services.generate_recurring(_current_month(), user_id=request.user.pk)
    messages.success(request, f"Cheltuieli generate pentru luna curentă: {created}.")
    return redirect("tenant:expense-list", tenant_id=tenant_id)
