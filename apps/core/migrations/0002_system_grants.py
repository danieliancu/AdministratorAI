from django.db import migrations

from apps.core.db.operations import GrantGlobal


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_app_schema"),
        ("auth", "__first__"),
        ("contenttypes", "__first__"),
        ("sessions", "__first__"),
    ]

    operations = [
        GrantGlobal("django_session", "SELECT, INSERT, UPDATE, DELETE"),
        GrantGlobal("django_content_type", "SELECT"),
        GrantGlobal("auth_permission", "SELECT"),
    ]
