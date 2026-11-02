from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import ImproperlyConfigured, PermissionDenied
from django.http import Http404

from apps.platform_admin.access import load_platform_access
from apps.tenants.access import load_tenant_access

from .db.scope import db_scope


def _run_view(view_func, request, view_args, view_kwargs):
    response = view_func(request, *view_args, **view_kwargs)
    # Render here: a lazy TemplateResponse would otherwise query after the scope has closed.
    if callable(getattr(response, "render", None)):
        response = response.render()
    if response.streaming:
        raise ImproperlyConfigured("Streaming responses cannot hold a database scope open")
    return response


class DbScopeMiddleware:
    """Open the database scope from the URL namespace, so no view can forget it."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        namespaces = request.resolver_match.namespaces
        namespace = namespaces[0] if namespaces else None
        if namespace == "public":
            return None
        if namespace not in ("account", "tenant", "platform"):
            raise ImproperlyConfigured(f"Route has no scope namespace: {request.path}")

        user = request.user
        if not user.is_authenticated:
            return redirect_to_login(request.get_full_path())

        if namespace == "platform":
            capability = getattr(view_func, "required_platform_capability", None)
            if capability is None:
                raise ImproperlyConfigured(f"Platform view declares no capability: {request.path}")
            with db_scope(user_id=user.pk):
                access = load_platform_access(user.pk)
            if access is None:
                # Non-staff cannot even learn that the platform area exists.
                raise Http404
            if not access.can(capability):
                raise PermissionDenied
            request.platform_access = access
            # No default-alias scope here: these views may only use the platform role.
            return _run_view(view_func, request, view_args, view_kwargs)

        if namespace == "account":
            with db_scope(user_id=user.pk):
                return _run_view(view_func, request, view_args, view_kwargs)

        capability = getattr(view_func, "required_capability", None)
        if capability is None:
            raise ImproperlyConfigured(f"Tenant view declares no capability: {request.path}")

        tenant_id = view_kwargs["tenant_id"]
        with db_scope(tenant_id=tenant_id, user_id=user.pk):
            access = load_tenant_access(user.pk)
            if access is None:
                # Same answer for "not a member" and "does not exist".
                raise Http404
            if not access.is_active or not access.can(capability):
                raise PermissionDenied
            request.tenant_access = access
            return _run_view(view_func, request, view_args, view_kwargs)
