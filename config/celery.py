import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

# Tasks refuse to run unless they declare a database scope.
app = Celery("administrator_ai", task_cls="apps.core.tasks:ScopedTask")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
