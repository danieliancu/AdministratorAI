from django.urls import path

from . import views

urlpatterns = [
    path("rapoarte/", views.report_summary, name="report-summary"),
    path("rapoarte/vanzari/", views.report_sales, name="report-sales"),
    path("rapoarte/cheltuieli/", views.report_expenses, name="report-expenses"),
    path("rapoarte/creante/", views.report_receivables, name="report-receivables"),
    path("rapoarte/stocuri/", views.report_inventory, name="report-inventory"),
    path("rapoarte/sold-initial/", views.opening_cash, name="opening-cash"),
]
