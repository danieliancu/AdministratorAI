from django.db import migrations


def context_function(name, setting, returns):
    # NULLIF: a transaction-local setting reverts to '', not NULL, once it has been used.
    cast = "::uuid" if returns == "uuid" else ""
    return f"""
        CREATE FUNCTION app.{name}() RETURNS {returns}
        LANGUAGE sql STABLE PARALLEL SAFE AS
        $$ SELECT NULLIF(pg_catalog.current_setting('{setting}', true), ''){cast} $$;
    """


class Migration(migrations.Migration):
    dependencies = []

    operations = [
        migrations.RunSQL(
            sql="CREATE SCHEMA app;"
            + context_function("current_tenant_id", "app.tenant_id", "uuid")
            + context_function("current_user_id", "app.user_id", "uuid")
            + context_function("lookup_email", "app.lookup_email", "text")
            + context_function("invite_token_hash", "app.invite_token_hash", "text")
            + "GRANT USAGE ON SCHEMA app TO aai_app;",
            reverse_sql="DROP SCHEMA app CASCADE;",
        ),
    ]
