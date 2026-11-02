from django import forms

from .models import ImportBatch


class UploadForm(forms.Form):
    kind = forms.ChoiceField(label="Ce imporți", choices=ImportBatch.Kind.choices)
    file = forms.FileField(label="Fișier .csv sau .xlsx, cel mult 5 MB și 5000 de rânduri")
