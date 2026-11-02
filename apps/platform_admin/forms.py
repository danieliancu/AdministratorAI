from django import forms

REASON_HELP = "Se păstrează în jurnalul de audit și este vizibil firmei."


class TenantCreateForm(forms.Form):
    name = forms.CharField(label="Numele firmei", max_length=200)
    owner_login = forms.CharField(
        label="Email-ul proprietarului",
        max_length=254,
        help_text="Proprietarul trebuie să aibă deja un cont.",
    )
    reason = forms.CharField(label="Motiv", max_length=500, help_text=REASON_HELP)


class TenantStatusForm(forms.Form):
    status = forms.ChoiceField(choices=[("active", "Activ"), ("suspended", "Suspendat")])
    reason = forms.CharField(label="Motiv", max_length=500, help_text=REASON_HELP)
