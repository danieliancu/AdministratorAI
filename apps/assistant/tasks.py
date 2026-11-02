from celery import shared_task

from apps.core.tasks import UnscopedTenantTask

from .answering import answer_message


@shared_task(base=UnscopedTenantTask, name="assistant.answer")
def answer(*, tenant_id, user_id, message_id):
    """Only the worker holds the provider key, so answers never run in a web request."""
    answer_message(message_id, tenant_id=tenant_id, user_id=user_id)
