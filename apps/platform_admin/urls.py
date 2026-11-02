from django.urls import path

from . import views

urlpatterns = [
    path("", views.overview, name="overview"),
    path("firme/", views.tenant_list, name="tenants"),
    path("firme/noua/", views.tenant_new, name="tenant-new"),
    path("firme/<uuid:tenant_id>/stare/", views.tenant_status, name="tenant-status"),
    path("utilizatori/", views.user_list, name="users"),
    path("audit/", views.audit_log, name="audit"),
]
