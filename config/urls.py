from django.urls import path

from apps.core import views as core_views

urlpatterns = [
    path("healthz/", core_views.healthz, name="healthz"),
    path("readyz/", core_views.readyz, name="readyz"),
]
