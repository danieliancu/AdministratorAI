from django.db import migrations

from apps.core.db.operations import EnableTenantRLS


class Migration(migrations.Migration):
    dependencies = [("inventory", "0001_initial")]

    operations = [
        EnableTenantRLS("inventory_product"),
        EnableTenantRLS("inventory_stockmovement"),
        # Stock history is append-only: a correction is a new movement.
        migrations.RunSQL(
            """
            REVOKE DELETE ON inventory_product FROM aai_app;
            REVOKE UPDATE, DELETE ON inventory_stockmovement FROM aai_app;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
