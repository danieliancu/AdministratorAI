from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from apps.core.db.scope import db_scope
from apps.core.throttle import Throttled, hit

from . import services
from .forms import LoginForm, PasswordResetRequestForm, RegistrationForm, SetPasswordForm
from .models import normalize_login

WINDOW = 15 * 60


def _throttled(request):
    return render(
        request,
        "accounts/throttled.html",
        status=429,
    )


def _client_ip(request):
    return request.META.get("REMOTE_ADDR", "")


def login_view(request):
    form = LoginForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():
        identifier = normalize_login(form.cleaned_data["identifier"])
        try:
            hit("login-ip", _client_ip(request), limit=50, window=WINDOW)
            hit("login-id", identifier, limit=10, window=WINDOW)
        except Throttled:
            return _throttled(request)
        user = authenticate(
            request, identifier=identifier, password=form.cleaned_data["password"]
        )
        if user is not None:
            # login() updates last_login, which only the user's own scope may write.
            with db_scope(user_id=user.pk):
                login(request, user)
            target = request.POST.get("next", "")
            if url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
                return redirect(target)
            return redirect("account:tenant-list")
        error = "Datele de autentificare nu sunt corecte."
    return render(
        request,
        "accounts/login.html",
        {"form": form, "error": error, "next": request.GET.get("next", "")},
    )


@require_POST
def logout_view(request):
    logout(request)
    return redirect("public:landing")


def register_view(request):
    form = RegistrationForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            hit("register-ip", _client_ip(request), limit=20, window=WINDOW)
        except Throttled:
            return _throttled(request)
        services.register_user(
            request,
            email=form.cleaned_data["email"],
            password=form.cleaned_data["password"],
            full_name=form.cleaned_data["full_name"],
        )
        return render(request, "accounts/check_email.html")
    return render(request, "accounts/register.html", {"form": form})


def verify_email_view(request, token):
    valid = services.verify_email(token)
    return render(request, "accounts/verified.html", {"valid": valid}, status=200 if valid else 400)


def password_reset_request_view(request):
    form = PasswordResetRequestForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            hit("reset-ip", _client_ip(request), limit=20, window=WINDOW)
            hit("reset-email", normalize_login(form.cleaned_data["email"]), limit=5, window=WINDOW)
        except Throttled:
            return _throttled(request)
        services.request_password_reset(request, form.cleaned_data["email"])
        return render(request, "accounts/check_email.html")
    return render(request, "accounts/password_reset.html", {"form": form})


def password_reset_confirm_view(request, user_id, token):
    user = services.load_user_for_reset(user_id, token)
    if user is None:
        return render(request, "accounts/verified.html", {"valid": False}, status=400)
    form = SetPasswordForm(request.POST or None, user=user)
    if request.method == "POST" and form.is_valid():
        services.set_new_password(user, form.cleaned_data["password"])
        messages.success(request, "Parola a fost schimbată. Te poți autentifica.")
        return redirect(reverse("public:login"))
    return render(request, "accounts/password_reset_confirm.html", {"form": form})
