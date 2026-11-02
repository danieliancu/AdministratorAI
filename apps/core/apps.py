from django.apps import AppConfig
from django.db.backends.signals import connection_created


class CoreConfig(AppConfig):
    name = "apps.core"

    def ready(self):
        from .db.guard import check_role_on_connect

        connection_created.connect(check_role_on_connect, dispatch_uid="aai_role_guard")
