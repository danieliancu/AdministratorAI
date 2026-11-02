from django import forms

from apps.core.forms import AmountsMixin, DateInput, StrictDecimalField, TenantModelForm

from . import services
from .models import Customer, Invoice, Payment, SaleTransaction


def _category_field():
    return forms.CharField(
        label="Categorie",
        required=False,
        max_length=100,
        widget=forms.TextInput(attrs={"list": "categories"}),
    )


class _CategoryName:
    """A category is typed, and created on first use, so it never interrupts data entry."""

    def _category_initial(self):
        category = self.instance.category if self.instance.category_id else None
        self.fields["category_name"].initial = category.name if category else ""

    def save(self, commit=True):
        self.instance.category = services.category_named(self.cleaned_data.get("category_name"))
        return super().save(commit)


class CustomerForm(TenantModelForm):
    class Meta:
        model = Customer
        fields = ["name", "cui", "email", "phone", "is_active"]

    def clean_cui(self):
        cui = self.cleaned_data["cui"].strip()
        if cui and Customer.objects.filter(cui=cui).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Există deja un client cu acest CUI.")
        return cui


class InvoiceForm(_CategoryName, AmountsMixin, TenantModelForm):
    net = StrictDecimalField(label="Valoare fără TVA")
    vat = StrictDecimalField(label="TVA")
    gross = StrictDecimalField(label="Total")
    category_name = _category_field()

    class Meta:
        model = Invoice
        fields = ["number", "customer", "issue_date", "due_date", "net", "vat", "gross", "notes"]
        widgets = {"issue_date": DateInput(), "due_date": DateInput()}

    def __init__(self, *args, paid=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.paid = paid
        self.fields["customer"].queryset = Customer.objects.filter(is_active=True)
        self._category_initial()

    def clean_number(self):
        number = self.cleaned_data["number"].strip()
        if Invoice.objects.filter(number=number).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Există deja o factură cu acest număr.")
        return number

    def clean(self):
        cleaned = super().clean()
        issue, due = cleaned.get("issue_date"), cleaned.get("due_date")
        if issue and due and due < issue:
            self.add_error("due_date", "Scadența nu poate fi înaintea datei emiterii.")
        gross = cleaned.get("gross")
        if self.paid and gross is not None and gross < self.paid:
            self.add_error("gross", f"Totalul nu poate fi sub suma deja încasată ({self.paid}).")
        return cleaned


class PaymentForm(forms.Form):
    date = forms.DateField(label="Data încasării", widget=DateInput())
    amount = StrictDecimalField(label="Sumă încasată")
    method = forms.ChoiceField(label="Metodă", choices=Payment.Method.choices)
    reference = forms.CharField(label="Referință", max_length=100, required=False)

    def clean_amount(self):
        amount = self.cleaned_data["amount"]
        if amount is None or amount <= 0:
            raise forms.ValidationError("Suma trebuie să fie mai mare decât zero.")
        return amount


class SaleForm(_CategoryName, AmountsMixin, TenantModelForm):
    net = StrictDecimalField(label="Valoare fără TVA")
    vat = StrictDecimalField(label="TVA")
    gross = StrictDecimalField(label="Total")
    category_name = _category_field()

    class Meta:
        model = SaleTransaction
        fields = ["date", "description", "customer", "net", "vat", "gross", "reference"]
        widgets = {"date": DateInput()}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["customer"].queryset = Customer.objects.filter(is_active=True)
        self._category_initial()
