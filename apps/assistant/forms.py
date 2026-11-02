from django import forms


class QuestionForm(forms.Form):
    question = forms.CharField(
        label="Întrebarea ta",
        max_length=1000,
        widget=forms.Textarea(
            attrs={"rows": 2, "placeholder": "Întreabă despre datele firmei sau despre legislație"}
        ),
    )
