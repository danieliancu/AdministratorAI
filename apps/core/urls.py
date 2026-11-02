from django.urls import path

from . import views

public_urlpatterns = [
    path("", views.landing, name="landing"),
    path("healthz/", views.healthz, name="healthz"),
    path("readyz/", views.readyz, name="readyz"),
]
