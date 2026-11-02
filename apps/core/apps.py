from django.apps import AppConfig
from django.db.backends.signals import connection_created


class CoreConfig(AppConfig):
    name = "apps.core"

    def ready(self):
        from .db import checks  # noqa: F401
        from .db.guard import check_role_on_connect, install_query_guard

        connection_created.connect(check_role_on_connect, dispatch_uid="aai_role_guard")
        connection_created.connect(install_query_guard, dispatch_uid="aai_query_guard")
