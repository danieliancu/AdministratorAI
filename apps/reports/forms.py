from django import forms
from django.utils import timezone

from apps.core.forms import DateInput, StrictDecimalField, TenantModelForm

from .models import OpeningCash


class OpeningCashForm(TenantModelForm):
    amount = StrictDecimalField(label="Sold de numerar și bancă")

    class Meta:
        model = OpeningCash
        fields = ["amount", "as_of"]
        widgets = {"as_of": DateInput()}
        labels = {"as_of": "La sfârșitul zilei de"}

    def clean_as_of(self):
        as_of = self.cleaned_data["as_of"]
        if as_of > timezone.localdate():
            raise forms.ValidationError("Soldul declarat nu poate fi din viitor.")
        return as_of
