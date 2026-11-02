from django.urls import path

from apps.expenses.urls import urlpatterns as expense_urls
from apps.financial_imports.urls import urlpatterns as import_urls
from apps.inventory.urls import urlpatterns as inventory_urls
from apps.reports.urls import urlpatterns as report_urls
from apps.sales.urls import urlpatterns as sales_urls

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
    *sales_urls,
    *expense_urls,
    *inventory_urls,
    *import_urls,
    *report_urls,
]
