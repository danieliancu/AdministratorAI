from django import forms

from .numbers import BadValue, parse_decimal


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, **kwargs):
        super().__init__(format="%Y-%m-%d", **kwargs)


class StrictDecimalField(forms.Field):
    """Accepts Romanian notation and refuses ambiguous numbers instead of guessing."""

    widget = forms.TextInput(attrs={"inputmode": "decimal", "autocomplete": "off"})

    def __init__(self, *, places=2, minimum=None, **kwargs):
        self.places = places
        self.minimum = minimum
        super().__init__(**kwargs)

    def to_python(self, value):
        if value in (None, ""):
            return None
        try:
            number = parse_decimal(value, places=self.places)
        except BadValue as exc:
            raise forms.ValidationError(str(exc)) from exc
        if self.minimum is not None and number < self.minimum:
            raise forms.ValidationError(f"Valoarea trebuie să fie cel puțin {self.minimum}.")
        return number

    def prepare_value(self, value):
        return str(value).replace(".", ",") if value not in (None, "") else value


class AmountsMixin:
    """Net + VAT must equal the total. The amounts are the user's; nothing is derived."""

    def clean(self):
        cleaned = super().clean()
        net, vat, gross = (cleaned.get(name) for name in ("net", "vat", "gross"))
        if net is not None and vat is not None and gross is not None:
            if net < 0 or vat < 0:
                self.add_error(
                    "gross", "Sumele nu pot fi negative. Stornările nu sunt încă acceptate."
                )
            elif net + vat != gross:
                self.add_error(
                    "gross", "Totalul trebuie să fie egal cu valoarea fără TVA plus TVA."
                )
            elif gross <= 0:
                self.add_error("gross", "Totalul trebuie să fie mai mare decât zero.")
        return cleaned


class TenantModelForm(forms.ModelForm):
    """Ties a new row to the tenant of the page. RLS would refuse any other tenant anyway."""

    def __init__(self, *args, tenant_id, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.tenant_id = tenant_id
        self.tenant_id = tenant_id

    def changes(self):
        """Old and new values of what the user changed, for the audit log."""
        return {
            name: [str(self.initial.get(name)), str(self.cleaned_data.get(name))]
            for name in self.changed_data
        }
