from django.urls import path

from . import views

urlpatterns = [
    path("", views.overview, name="overview"),
    path("firme/", views.tenant_list, name="tenants"),
    path("firme/noua/", views.tenant_new, name="tenant-new"),
    path("firme/<uuid:tenant_id>/stare/", views.tenant_status, name="tenant-status"),
    path("utilizatori/", views.user_list, name="users"),
    path("audit/", views.audit_log, name="audit"),
    path("legislatie/surse/", views.legal_sources, name="legal-sources"),
    path(
        "legislatie/surse/<str:key>/stare/",
        views.legal_source_toggle,
        name="legal-source-toggle",
    ),
    path("legislatie/actualizari/", views.legal_changes, name="legal-changes"),
    path(
        "legislatie/actualizari/<uuid:change_id>/decizie/",
        views.legal_change_review,
        name="legal-change-review",
    ),
    path("ai/", views.ai_usage, name="ai-usage"),
    path("ai/costuri/", views.ai_costs, name="ai-costs"),
    path("ai/politica/<uuid:tenant_id>/", views.ai_policy, name="ai-policy"),
    path("ai/rezervari/<uuid:reservation_id>/", views.ai_resolve, name="ai-resolve"),
    path("ai/reconciliere/", views.ai_reconcile, name="ai-reconcile"),
]
