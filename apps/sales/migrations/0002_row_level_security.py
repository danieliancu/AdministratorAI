from django.db import migrations

from apps.core.db.operations import EnableTenantRLS


class Migration(migrations.Migration):
    dependencies = [("sales", "0001_initial")]

    operations = [
        EnableTenantRLS("sales_customer"),
        EnableTenantRLS("sales_salescategory"),
        EnableTenantRLS("sales_invoice"),
        EnableTenantRLS("sales_payment"),
        EnableTenantRLS("sales_saletransaction"),
        # Financial records are cancelled, never erased.
        migrations.RunSQL(
            """
            REVOKE DELETE ON sales_customer FROM aai_app;
            REVOKE DELETE ON sales_invoice FROM aai_app;
            REVOKE DELETE ON sales_payment FROM aai_app;
            REVOKE DELETE ON sales_saletransaction FROM aai_app;
            """,
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
