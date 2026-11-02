from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError


class LoginForm(forms.Form):
    identifier = forms.CharField(label="Email sau utilizator", max_length=254)
    password = forms.CharField(label="Parolă", widget=forms.PasswordInput, strip=False)


class RegistrationForm(forms.Form):
    full_name = forms.CharField(label="Nume complet", max_length=200)
    email = forms.EmailField(label="Email")
    password = forms.CharField(label="Parolă", widget=forms.PasswordInput, strip=False)

    def clean_password(self):
        password = self.cleaned_data["password"]
        validate_password(password)
        return password


class PasswordResetRequestForm(forms.Form):
    email = forms.EmailField(label="Email")


class SetPasswordForm(forms.Form):
    password = forms.CharField(label="Parolă nouă", widget=forms.PasswordInput, strip=False)
    password_again = forms.CharField(
        label="Repetă parola", widget=forms.PasswordInput, strip=False
    )

    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        if password and password != cleaned.get("password_again"):
            raise ValidationError("Parolele nu coincid.")
        if password:
            validate_password(password, self.user)
        return cleaned
