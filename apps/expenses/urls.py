from django.urls import path

from . import views

urlpatterns = [
    path("cheltuieli/", views.expense_list, name="expense-list"),
    path("cheltuieli/noua/", views.expense_new, name="expense-new"),
    path("cheltuieli/documente/<uuid:pk>/", views.document_download, name="document-download"),
    path("cheltuieli/recurente/", views.recurring_list, name="recurring-list"),
    path("cheltuieli/recurente/noua/", views.recurring_new, name="recurring-new"),
    path("cheltuieli/recurente/generare/", views.recurring_generate, name="recurring-generate"),
    path("cheltuieli/recurente/<uuid:pk>/editare/", views.recurring_edit, name="recurring-edit"),
    path("cheltuieli/<uuid:pk>/", views.expense_detail, name="expense-detail"),
    path("cheltuieli/<uuid:pk>/editare/", views.expense_edit, name="expense-edit"),
    path("cheltuieli/<uuid:pk>/anulare/", views.expense_void, name="expense-void"),
]
