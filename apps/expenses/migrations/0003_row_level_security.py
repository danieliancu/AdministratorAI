from django.db import migrations

from apps.core.db.operations import EnableTenantRLS


class Migration(migrations.Migration):
    dependencies = [("expenses", "0002_initial")]

    operations = [
        EnableTenantRLS("expenses_expensecategory"),
        EnableTenantRLS("expenses_recurringexpense"),
        EnableTenantRLS("expenses_expense"),
        EnableTenantRLS("expenses_expensedocument"),
        migrations.RunSQL(
            """
            REVOKE DELETE ON expenses_expense FROM aai_app;
            REVOKE UPDATE, DELETE ON expenses_expensedocument FROM aai_app;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
