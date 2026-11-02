from django.db import migrations

from apps.core.db.operations import CURRENT_TENANT

TABLES = ("audit_tenantevent", "audit_securityevent", "audit_platformevent")

FUNCTIONS = """
    CREATE FUNCTION app.audit_stamp() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        NEW.occurred_at := pg_catalog.clock_timestamp();
        NEW.db_role := current_user;
        RETURN NEW;
    END $$;
    CREATE FUNCTION app.audit_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
        RAISE EXCEPTION 'audit events are append-only' USING ERRCODE = '42501';
    END $$;
"""


def protect(table):
    return f"""
        ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
        ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
        CREATE TRIGGER {table}_stamp BEFORE INSERT ON {table}
            FOR EACH ROW EXECUTE FUNCTION app.audit_stamp();
        CREATE TRIGGER {table}_no_change BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION app.audit_immutable();
        CREATE TRIGGER {table}_no_truncate BEFORE TRUNCATE ON {table}
            FOR EACH STATEMENT EXECUTE FUNCTION app.audit_immutable();
    """


# No UPDATE or DELETE policy or grant exists for any role. aai_platform never touches
# these tables directly: it goes through the platform schema.
APP_ACCESS = f"""
    CREATE POLICY tenantevent_sel ON audit_tenantevent FOR SELECT TO aai_app
        USING (tenant_id = {CURRENT_TENANT});
    CREATE POLICY tenantevent_ins ON audit_tenantevent FOR INSERT TO aai_app
        WITH CHECK (tenant_id = {CURRENT_TENANT});
    GRANT SELECT, INSERT ON audit_tenantevent TO aai_app;
    CREATE POLICY securityevent_ins ON audit_securityevent FOR INSERT TO aai_app
        WITH CHECK (true);
    GRANT INSERT ON audit_securityevent TO aai_app;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_app_schema"),
        ("audit", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(FUNCTIONS + "".join(protect(t) for t in TABLES), migrations.RunSQL.noop),
        migrations.RunSQL(APP_ACCESS, migrations.RunSQL.noop),
    ]
