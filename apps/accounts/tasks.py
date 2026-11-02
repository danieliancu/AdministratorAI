from celery import shared_task
from django.core.management import call_command

from apps.core.tasks import SystemTask


@shared_task(base=SystemTask, name="accounts.clear_expired_sessions")
def clear_expired_sessions():
    call_command("clearsessions")
