from django.urls import path

from . import views

urlpatterns = [
    path("stocuri/", views.product_list, name="product-list"),
    path("stocuri/produse/nou/", views.product_new, name="product-new"),
    path("stocuri/produse/<uuid:pk>/", views.product_detail, name="product-detail"),
    path("stocuri/produse/<uuid:pk>/editare/", views.product_edit, name="product-edit"),
]
