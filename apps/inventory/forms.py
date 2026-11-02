from django import forms
from django.utils import timezone

from apps.core.forms import DateInput, StrictDecimalField, TenantModelForm

from .models import Product, StockMovement


class ProductForm(TenantModelForm):
    reorder_threshold = StrictDecimalField(
        label="Prag de reaprovizionare", places=3, minimum=0, required=False
    )
    unit_cost = StrictDecimalField(label="Cost unitar declarat", minimum=0, required=False)

    class Meta:
        model = Product
        fields = ["sku", "name", "unit", "reorder_threshold", "unit_cost", "is_active"]

    def clean_sku(self):
        sku = self.cleaned_data["sku"].strip()
        if Product.objects.filter(sku=sku).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Există deja un produs cu acest cod.")
        return sku


class MovementForm(forms.Form):
    date = forms.DateField(label="Data", widget=DateInput(), initial=timezone.localdate)
    kind = forms.ChoiceField(label="Tip", choices=StockMovement.Kind.choices)
    quantity = StrictDecimalField(
        label="Cantitate",
        places=3,
        help_text="Pozitivă pentru intrări și ieșiri. La ajustare poate fi și negativă.",
    )
    reference = forms.CharField(label="Referință", max_length=100, required=False)
