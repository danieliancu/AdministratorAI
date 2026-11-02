from celery import shared_task

from apps.core.tasks import UnscopedTenantTask

from .gateway import AIError, AIRequest, execute


@shared_task(base=UnscopedTenantTask, name="ai_gateway.run_diagnostic")
def run_diagnostic(*, tenant_id, user_id, idempotency_key, note):
    """Exercises the whole gateway from the application. The outcome is in the usage records."""
    try:
        execute(
            AIRequest(
                tenant_id=tenant_id,
                user_id=user_id,
                operation="diagnostic.echo",
                idempotency_key=idempotency_key,
                variables={"note": note},
            )
        )
    except AIError as exc:
        return type(exc).__name__
    return "ok"
