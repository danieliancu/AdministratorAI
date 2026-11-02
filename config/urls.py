from django.urls import include, path

from apps.accounts import urls as account_urls
from apps.core import urls as core_urls
from apps.tenants import urls as tenant_urls

# The first namespace decides the database scope of a request (see DbScopeMiddleware).
urlpatterns = [
    path("", include((core_urls.public_urlpatterns + account_urls.public_urlpatterns, "public"))),
    path(
        "cont/",
        include((account_urls.account_urlpatterns + tenant_urls.account_urlpatterns, "account")),
    ),
    path("t/<uuid:tenant_id>/", include((tenant_urls.tenant_urlpatterns, "tenant"))),
]
