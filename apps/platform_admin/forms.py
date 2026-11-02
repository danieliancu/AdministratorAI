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


class AIPolicyForm(forms.Form):
    monthly_limit = forms.DecimalField(label="Buget lunar (USD)", min_value=0, decimal_places=8)
    overage_authorised = forms.BooleanField(label="Depășire plătită autorizată", required=False)
    overage_limit = forms.DecimalField(
        label="Limită depășire (USD)", min_value=0, decimal_places=8, initial=0
    )
    max_cost_per_request = forms.DecimalField(
        label="Cost maxim pe cerere (USD)", min_value=0, decimal_places=8
    )
    max_output_tokens = forms.IntegerField(label="Tokeni de ieșire maximi", min_value=1)
    user_daily_limit = forms.DecimalField(
        label="Limită zilnică per utilizator (USD)", min_value=0, decimal_places=8, required=False
    )
    user_monthly_limit = forms.DecimalField(
        label="Limită lunară per utilizator (USD)", min_value=0, decimal_places=8, required=False
    )
    requests_per_minute = forms.IntegerField(label="Cereri pe minut", min_value=1, initial=30)
    billing_anchor_day = forms.IntegerField(
        label="Ziua de început a perioadei", min_value=1, max_value=28, initial=1
    )
    allowed_models = forms.MultipleChoiceField(
        label="Modele permise", widget=forms.CheckboxSelectMultiple, required=False
    )
    allowed_operations = forms.MultipleChoiceField(
        label="Operații permise", widget=forms.CheckboxSelectMultiple, required=False
    )
    reason = forms.CharField(
        label="Motiv",
        max_length=500,
        help_text="Se păstrează în jurnalul de audit al platformei. Firma nu îl vede.",
    )

    def __init__(self, *args, catalog, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["allowed_models"].choices = [(m, m) for m in catalog["models"]]
        self.fields["allowed_operations"].choices = [(o, o) for o in catalog["operations"]]


class ReconciliationForm(forms.Form):
    provider = forms.CharField(label="Provider", max_length=40)
    start = forms.DateTimeField(label="De la (AAAA-LL-ZZ HH:MM)")
    end = forms.DateTimeField(label="Până la (AAAA-LL-ZZ HH:MM)")
    reported = forms.DecimalField(label="Cost raportat de provider", min_value=0, decimal_places=8)
    currency = forms.CharField(label="Monedă", max_length=3, initial="USD")
    note = forms.CharField(label="Notă, de exemplu numărul facturii", max_length=500)
