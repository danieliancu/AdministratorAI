from django.urls import path

from . import views

urlpatterns = [
    path("importuri/", views.import_list, name="import-list"),
    path("importuri/model/<str:kind>/", views.import_template, name="import-template"),
    path("importuri/<uuid:pk>/", views.import_detail, name="import-detail"),
    path("importuri/<uuid:pk>/confirmare/", views.import_commit, name="import-commit"),
    path("importuri/<uuid:pk>/renuntare/", views.import_discard, name="import-discard"),
    path("importuri/<uuid:pk>/respinse/", views.import_rejected, name="import-rejected"),
]
