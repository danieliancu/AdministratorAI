import uuid

from django import forms

from .models import CompanyFiscalProfile, Tenant
from .roles import Role


class TenantCreateForm(forms.Form):
    name = forms.CharField(label="Numele firmei", max_length=200)
    # Generated with the page, so a double submit creates a single tenant.
    idempotency_key = forms.UUIDField(widget=forms.HiddenInput, initial=uuid.uuid4)


class TenantNameForm(forms.ModelForm):
    class Meta:
        model = Tenant
        fields = ["name"]
        labels = {"name": "Numele firmei"}


class InviteForm(forms.Form):
    email = forms.EmailField(label="Email")
    # An Owner is only ever the creator of the tenant.
    role = forms.ChoiceField(
        label="Rol", choices=[c for c in Role.choices if c[0] != Role.OWNER]
    )


class FiscalProfileForm(forms.ModelForm):
    class Meta:
        model = CompanyFiscalProfile
        fields = [
            "company_name",
            "cui",
            "registration_number",
            "caen_codes",
            "fiscal_regime",
            "vat_status",
        ]
        labels = {"company_name": "Denumire firmă"}
