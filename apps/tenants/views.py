from django.contrib import messages
from django.core.mail import send_mail
from django.db import transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from . import roles, services
from .forms import FiscalProfileForm, InviteForm, TenantCreateForm, TenantNameForm
from .models import CompanyFiscalProfile, Tenant, TenantInvitation, TenantMembership
from .roles import requires


def tenant_list(request):
    memberships = list(
        TenantMembership.objects.select_related("tenant")
        .filter(user=request.user, is_active=True)
        .order_by("tenant__name")
    )
    if len(memberships) == 1:
        return redirect("tenant:dashboard", tenant_id=memberships[0].tenant_id)
    return render(request, "tenants/tenant_list.html", {"memberships": memberships})


def tenant_new(request):
    form = TenantCreateForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():
        try:
            tenant = services.create_tenant(
                request.user,
                name=form.cleaned_data["name"],
                idempotency_key=form.cleaned_data["idempotency_key"],
            )
        except services.EmailNotVerified:
            error = "Confirmă-ți adresa de email înainte de a crea o firmă."
        except services.QuotaExceeded:
            error = "Ai atins numărul maxim de firme pentru acest cont."
        else:
            return redirect("tenant:dashboard", tenant_id=tenant.pk)
    return render(request, "tenants/tenant_new.html", {"form": form, "error": error})


def invitation_accept(request, token):
    error = None
    if request.method == "POST":
        try:
            tenant_id = services.accept_invitation(request.user, token)
        except services.EmailNotVerified:
            error = "Confirmă-ți adresa de email înainte de a accepta invitația."
        except services.InvitationInvalid:
            error = "Invitația nu este validă, a expirat sau a fost deja folosită."
        else:
            return redirect("tenant:dashboard", tenant_id=tenant_id)
    return render(request, "tenants/invitation.html", {"error": error})


@requires(roles.VIEW_DASHBOARD)
def dashboard(request, tenant_id):
    can_see_profile = request.tenant_access.can(roles.VIEW_FISCAL_PROFILE)
    profile = CompanyFiscalProfile.objects.first() if can_see_profile else None
    return render(
        request,
        "tenants/dashboard.html",
        {
            "profile_incomplete": profile is not None and not profile.cui,
            "can_edit_profile": request.tenant_access.can(roles.EDIT_FISCAL_PROFILE),
        },
    )


@requires(roles.VIEW_FISCAL_PROFILE)
def fiscal_profile(request, tenant_id):
    profile = CompanyFiscalProfile.objects.get()
    can_edit = request.tenant_access.can(roles.EDIT_FISCAL_PROFILE)
    form = FiscalProfileForm(request.POST if can_edit and request.method == "POST" else None,
                             instance=profile)
    if can_edit and request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.provenance = CompanyFiscalProfile.Provenance.USER_DECLARED
        saved.updated_at = timezone.now()
        saved.save()
        messages.success(request, "Profilul fiscal a fost salvat.")
        return redirect("tenant:fiscal-profile", tenant_id=tenant_id)
    return render(
        request, "tenants/fiscal_profile.html", {"form": form, "can_edit": can_edit}
    )


@requires(roles.MANAGE_SETTINGS)
def tenant_settings(request, tenant_id):
    tenant = Tenant.objects.get(pk=tenant_id)
    form = TenantNameForm(request.POST or None, instance=tenant)
    if request.method == "POST" and form.is_valid():
        # update_fields: the application role may write this column and not tenant status.
        form.save(commit=False).save(update_fields=["name"])
        messages.success(request, "Setările au fost salvate.")
        return redirect("tenant:settings", tenant_id=tenant_id)
    return render(request, "tenants/settings.html", {"form": form})


@requires(roles.MANAGE_MEMBERS)
def members(request, tenant_id):
    form = InviteForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        email = form.cleaned_data["email"]
        token = services.invite_member(
            tenant_id=tenant_id,
            invited_by_membership_id=request.tenant_access.membership_id,
            email=email,
            role=form.cleaned_data["role"],
        )
        link = request.build_absolute_uri(reverse("account:invitation-accept", args=[token]))
        name = request.tenant_access.tenant_name
        transaction.on_commit(
            lambda: send_mail(
                "Invitație în Administrator AI",
                f"Ai fost invitat(ă) în {name}.\n\nAcceptă invitația:\n{link}\n\n"
                f"Linkul expiră în {services.INVITATION_DAYS} zile.",
                None,
                [email],
            )
        )
        messages.success(request, f"Invitația a fost trimisă către {email}.")
        return redirect("tenant:members", tenant_id=tenant_id)
    return render(
        request,
        "tenants/members.html",
        {
            "form": form,
            "memberships": TenantMembership.objects.select_related("user").order_by("created_at"),
            "invitations": TenantInvitation.objects.filter(accepted_at__isnull=True),
        },
    )
