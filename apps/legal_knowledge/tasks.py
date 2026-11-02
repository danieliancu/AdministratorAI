from celery import shared_task

from apps.core.tasks import SystemTask

from .embedding import embed_pending
from .sync import run_due_sources


@shared_task(base=SystemTask, name="legal.sync_due_sources")
def sync_due_sources():
    jobs = run_due_sources()
    if any(job.new_documents for job in jobs):
        embed_pending()
    return len(jobs)
