from django import forms

from apps.core.forms import AmountsMixin, DateInput, StrictDecimalField, TenantModelForm

from . import services
from .models import Expense, RecurringExpense


class _CategoryName:
    def _category_initial(self):
        category = self.instance.category if self.instance.category_id else None
        self.fields["category_name"].initial = category.name if category else ""

    def save(self, commit=True):
        self.instance.category = services.category_named(self.cleaned_data.get("category_name"))
        return super().save(commit)


def _category_field():
    return forms.CharField(
        label="Categorie",
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"list": "categories"}),
    )


def _month_field(label, required=True):
    return forms.DateField(
        label=label,
        required=required,
        input_formats=["%Y-%m"],
        widget=forms.DateInput(format="%Y-%m", attrs={"type": "month"}),
    )


class ExpenseForm(_CategoryName, AmountsMixin, TenantModelForm):
    net = StrictDecimalField(label="Valoare fără TVA")
    vat = StrictDecimalField(label="TVA")
    gross = StrictDecimalField(label="Total")
    category_name = _category_field()

    class Meta:
        model = Expense
        fields = [
            "date",
            "supplier",
            "document_number",
            "description",
            "net",
            "vat",
            "gross",
            "paid_date",
        ]
        widgets = {"date": DateInput(), "paid_date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["paid_date"].label = "Data plății (gol dacă nu e plătită)"
        self._category_initial()


class RecurringForm(_CategoryName, AmountsMixin, TenantModelForm):
    net = StrictDecimalField(label="Valoare fără TVA")
    vat = StrictDecimalField(label="TVA")
    gross = StrictDecimalField(label="Total")
    category_name = _category_field()
    first_month = _month_field("Prima lună")
    last_month = _month_field("Ultima lună (opțional)", required=False)

    class Meta:
        model = RecurringExpense
        fields = [
            "description",
            "supplier",
            "net",
            "vat",
            "gross",
            "day_of_month",
            "first_month",
            "last_month",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._category_initial()

    def clean_day_of_month(self):
        day = self.cleaned_data["day_of_month"]
        if not 1 <= day <= 28:
            raise forms.ValidationError("Alege o zi între 1 și 28, ca să existe în fiecare lună.")
        return day

    def clean(self):
        cleaned = super().clean()
        first, last = cleaned.get("first_month"), cleaned.get("last_month")
        if first and last and last < first:
            self.add_error("last_month", "Ultima lună nu poate fi înaintea primei.")
        return cleaned


class DocumentForm(forms.Form):
    file = forms.FileField(label="Document justificativ (PDF, PNG sau JPEG, cel mult 10 MB)")
