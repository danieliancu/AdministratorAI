from django.urls import path

from . import views

account_urlpatterns = [
    path("firme/", views.tenant_list, name="tenant-list"),
    path("firme/noua/", views.tenant_new, name="tenant-new"),
    path("invitatii/<str:token>/", views.invitation_accept, name="invitation-accept"),
]

tenant_urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("profil-fiscal/", views.fiscal_profile, name="fiscal-profile"),
    path("membri/", views.members, name="members"),
    path("setari/", views.tenant_settings, name="settings"),
]
