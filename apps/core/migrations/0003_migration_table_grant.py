from django.db import migrations

from apps.core.db.operations import GrantGlobal


class Migration(migrations.Migration):
    dependencies = [("core", "0002_system_grants")]

    operations = [
        # runserver and readiness tooling compare applied migrations at startup.
        GrantGlobal("django_migrations", "SELECT"),
    ]
