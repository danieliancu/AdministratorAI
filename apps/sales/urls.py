from django.urls import path

from . import views

urlpatterns = [
    path("vanzari/", views.invoice_list, name="invoice-list"),
    path("vanzari/facturi/noua/", views.invoice_new, name="invoice-new"),
    path("vanzari/facturi/<uuid:pk>/", views.invoice_detail, name="invoice-detail"),
    path("vanzari/facturi/<uuid:pk>/editare/", views.invoice_edit, name="invoice-edit"),
    path("vanzari/facturi/<uuid:pk>/anulare/", views.invoice_cancel, name="invoice-cancel"),
    path("vanzari/incasari/<uuid:pk>/anulare/", views.payment_void, name="payment-void"),
    path("vanzari/fara-factura/", views.sale_list, name="sale-list"),
    path("vanzari/fara-factura/noua/", views.sale_new, name="sale-new"),
    path("vanzari/fara-factura/<uuid:pk>/editare/", views.sale_edit, name="sale-edit"),
    path("vanzari/fara-factura/<uuid:pk>/anulare/", views.sale_void, name="sale-void"),
    path("vanzari/clienti/", views.customer_list, name="customer-list"),
    path("vanzari/clienti/nou/", views.customer_new, name="customer-new"),
    path("vanzari/clienti/<uuid:pk>/editare/", views.customer_edit, name="customer-edit"),
]
