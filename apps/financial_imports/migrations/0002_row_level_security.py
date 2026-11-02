from django.db import migrations

from apps.core.db.operations import EnableTenantRLS


class Migration(migrations.Migration):
    dependencies = [("financial_imports", "0001_initial")]

    operations = [
        EnableTenantRLS("financial_imports_importbatch"),
        EnableTenantRLS("financial_imports_importrow"),
        # Original rows stay as they were read: only the outcome columns can change.
        migrations.RunSQL(
            """
            REVOKE DELETE ON financial_imports_importbatch FROM aai_app;
            REVOKE UPDATE, DELETE ON financial_imports_importrow FROM aai_app;
            GRANT UPDATE (status, errors, target_id) ON financial_imports_importrow TO aai_app;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
