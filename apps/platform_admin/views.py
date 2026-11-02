from django.contrib import messages
from django.core.paginator import Paginator
from django.db import DatabaseError
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from . import services
from .access import MANAGE, VIEW, requires_platform
from .forms import TenantCreateForm, TenantStatusForm

PAGE_SIZE = 25


def _page(request, rows):
    return Paginator(rows, PAGE_SIZE).get_page(request.GET.get("pagina"))


@requires_platform(VIEW)
def overview(request):
    return render(request, "platform/overview.html", {"counts": services.counts()})


@requires_platform(VIEW)
def tenant_list(request):
    search = request.GET.get("q", "").strip()
    return render(
        request,
        "platform/tenants.html",
        {
            "page": _page(request, services.tenants(search)),
            "search": search,
            "status_form": TenantStatusForm(),
            "can_manage": request.platform_access.can(MANAGE),
        },
    )


@requires_platform(MANAGE)
def tenant_new(request):
    form = TenantCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.create_tenant(
                request.user.pk,
                name=form.cleaned_data["name"],
                owner_login=form.cleaned_data["owner_login"],
                reason=form.cleaned_data["reason"],
            )
        except DatabaseError:
            form.add_error("owner_login", "Nu există un cont cu această adresă.")
        else:
            messages.success(request, "Firma a fost creată.")
            return redirect("platform:tenants")
    return render(request, "platform/tenant_new.html", {"form": form})


@require_POST
@requires_platform(MANAGE)
def tenant_status(request, tenant_id):
    form = TenantStatusForm(request.POST)
    if form.is_valid():
        services.set_tenant_status(
            request.user.pk, tenant_id, form.cleaned_data["status"], form.cleaned_data["reason"]
        )
        messages.success(request, "Starea firmei a fost schimbată.")
    else:
        messages.error(request, "Motivul este obligatoriu.")
    return redirect("platform:tenants")


@requires_platform(VIEW)
def user_list(request):
    return render(request, "platform/users.html", {"page": _page(request, services.users())})


@requires_platform(VIEW)
def audit_log(request):
    return render(request, "platform/audit.html", {"page": _page(request, services.audit_log())})
