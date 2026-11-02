from django.db import migrations

from apps.core.db.operations import EnableTenantRLS


class Migration(migrations.Migration):
    dependencies = [("reports", "0001_initial")]

    operations = [EnableTenantRLS("reports_openingcash")]
