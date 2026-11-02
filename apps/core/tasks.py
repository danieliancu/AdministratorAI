from celery import Task
from celery.exceptions import Reject
from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from .db.scope import current_scope, db_scope


class ScopedTask(Task):
    """Default task base: a task must say which database scope it runs in."""

    scope = None

    def __call__(self, *args, **kwargs):
        if self.scope == "system" or self.name.startswith("celery."):
            return self.run(*args, **kwargs)
        raise ImproperlyConfigured(f"Task {self.name} declares no scope")


class TenantTask(ScopedTask):
    """Restores the tenant context captured by enqueue(). Runs in one transaction."""

    scope = "tenant"
    # Celery would otherwise check the context kwargs against the task's own signature.
    typing = False

    def __call__(self, *args, _tenant_id=None, _actor_id=None, **kwargs):
        from apps.tenants.models import Tenant

        if _tenant_id is None:
            # Never retried: without context the task could not see any data anyway.
            raise Reject("Tenant task without tenant context", requeue=False)
        with db_scope(tenant_id=_tenant_id, user_id=_actor_id):
            if not Tenant.objects.filter(pk=_tenant_id, status=Tenant.Status.ACTIVE).exists():
                return None
            return self.run(*args, **kwargs)


class SystemTask(ScopedTask):
    """Runs with no tenant context, so row-level security shows it no tenant data."""

    scope = "system"


def enqueue(task, *args, **kwargs):
    """Queue a tenant task from inside a tenant scope, after the transaction commits."""
    scope = current_scope()
    if scope is None or scope.tenant_id is None:
        raise ImproperlyConfigured("enqueue() needs an active tenant scope")
    context = {
        "_tenant_id": str(scope.tenant_id),
        "_actor_id": str(scope.user_id) if scope.user_id else None,
    }
    transaction.on_commit(lambda: task.apply_async(args=args, kwargs={**kwargs, **context}))
