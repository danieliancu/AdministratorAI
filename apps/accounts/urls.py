from django.urls import path

from . import views

public_urlpatterns = [
    path("autentificare/", views.login_view, name="login"),
    path("inregistrare/", views.register_view, name="register"),
    path("verificare-email/<str:token>/", views.verify_email_view, name="verify-email"),
    path("resetare-parola/", views.password_reset_request_view, name="password-reset"),
    path(
        "resetare-parola/<uuid:user_id>/<str:token>/",
        views.password_reset_confirm_view,
        name="password-reset-confirm",
    ),
]

account_urlpatterns = [
    path("iesire/", views.logout_view, name="logout"),
]
