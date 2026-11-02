from celery import shared_task

from apps.audit.services import record_tenant_event
from apps.core.db.scope import current_scope
from apps.core.tasks import TenantTask


@shared_task(base=TenantTask, name="tenants.record_context_probe")
def record_context_probe():
    """Operational check that a worker really receives tenant context. See deployment docs."""
    scope = current_scope()
    record_tenant_event("diagnostic.worker_context", actor_user_id=scope.user_id)
    return str(scope.tenant_id)
