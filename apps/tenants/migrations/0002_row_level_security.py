from django.db import migrations

from apps.core.db.operations import CURRENT_TENANT, EnableRLS, EnableTenantRLS

CURRENT_USER = "(SELECT app.current_user_id())"
ROLES = "aai_app, aai_owner"

MEMBERSHIP_POLICIES = f"""
    -- Identity mode (no tenant) lists my own memberships; the two modes are exclusive,
    -- so my rows in tenant B never appear while working inside tenant A.
    CREATE POLICY membership_sel ON tenants_tenantmembership FOR SELECT TO {ROLES} USING (
        tenant_id = {CURRENT_TENANT}
        OR ({CURRENT_TENANT} IS NULL AND user_id = {CURRENT_USER})
    );
    CREATE POLICY membership_ins ON tenants_tenantmembership FOR INSERT TO {ROLES}
        WITH CHECK (tenant_id = {CURRENT_TENANT});
    CREATE POLICY membership_upd ON tenants_tenantmembership FOR UPDATE TO {ROLES}
        USING (tenant_id = {CURRENT_TENANT}) WITH CHECK (tenant_id = {CURRENT_TENANT});
    CREATE POLICY membership_del ON tenants_tenantmembership FOR DELETE TO {ROLES}
        USING (tenant_id = {CURRENT_TENANT});
    GRANT SELECT, INSERT, UPDATE, DELETE ON tenants_tenantmembership TO aai_app;
"""

TENANT_POLICIES = f"""
    CREATE POLICY tenant_sel ON tenants_tenant FOR SELECT TO aai_app USING (
        id = {CURRENT_TENANT}
        OR ({CURRENT_TENANT} IS NULL AND id IN (SELECT tenant_id FROM tenants_tenantmembership))
    );
    -- Backfills enumerate tenants as the owner, one tenant scope at a time.
    CREATE POLICY tenant_sel_owner ON tenants_tenant FOR SELECT TO aai_owner USING (true);
    CREATE POLICY tenant_ins ON tenants_tenant FOR INSERT TO aai_app
        WITH CHECK (id = {CURRENT_TENANT} AND status = 'active' AND created_by_id = {CURRENT_USER});
    CREATE POLICY tenant_upd ON tenants_tenant FOR UPDATE TO aai_app
        USING (id = {CURRENT_TENANT}) WITH CHECK (id = {CURRENT_TENANT});
    -- Column grants: the application can rename a tenant, never lift its own suspension.
    GRANT SELECT, INSERT ON tenants_tenant TO aai_app;
    GRANT UPDATE (name) ON tenants_tenant TO aai_app;
"""

USER_POLICIES = f"""
    -- A user row is visible to itself, to a caller that already names its email, and
    -- to members of the current tenant. Nothing else can be enumerated.
    CREATE POLICY user_sel ON accounts_user FOR SELECT TO {ROLES} USING (
        id = {CURRENT_USER}
        OR email = (SELECT app.lookup_email())
        OR id IN (SELECT user_id FROM tenants_tenantmembership WHERE tenant_id = {CURRENT_TENANT})
    );
    CREATE POLICY user_ins ON accounts_user FOR INSERT TO {ROLES}
        WITH CHECK (id = {CURRENT_USER});
    CREATE POLICY user_upd ON accounts_user FOR UPDATE TO {ROLES}
        USING (id = {CURRENT_USER}) WITH CHECK (id = {CURRENT_USER});
    GRANT SELECT, INSERT, UPDATE ON accounts_user TO aai_app;
"""

INVITATION_POLICIES = f"""
    CREATE POLICY invitation_sel ON tenants_tenantinvitation FOR SELECT TO {ROLES} USING (
        tenant_id = {CURRENT_TENANT}
        OR ({CURRENT_TENANT} IS NULL AND token_hash = (SELECT app.invite_token_hash()))
    );
    CREATE POLICY invitation_ins ON tenants_tenantinvitation FOR INSERT TO {ROLES}
        WITH CHECK (tenant_id = {CURRENT_TENANT});
    CREATE POLICY invitation_upd ON tenants_tenantinvitation FOR UPDATE TO {ROLES}
        USING (tenant_id = {CURRENT_TENANT}) WITH CHECK (tenant_id = {CURRENT_TENANT});
    CREATE POLICY invitation_del ON tenants_tenantinvitation FOR DELETE TO {ROLES}
        USING (tenant_id = {CURRENT_TENANT});
    GRANT SELECT, INSERT, UPDATE, DELETE ON tenants_tenantinvitation TO aai_app;
"""

# Closes the worst failure: a bug that enters some tenant's context and adds itself as Owner.
MEMBERSHIP_TRIGGER = """
    CREATE FUNCTION app.check_membership_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE
        actor uuid := app.current_user_id();
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM tenants_tenantmembership m WHERE m.tenant_id = NEW.tenant_id)
           AND NEW.user_id = actor AND NEW.role = 'owner'
           AND EXISTS (SELECT 1 FROM tenants_tenant t
                       WHERE t.id = NEW.tenant_id AND t.created_by_id = actor) THEN
            RETURN NEW;
        END IF;
        IF EXISTS (SELECT 1 FROM tenants_tenantmembership m
                   WHERE m.tenant_id = NEW.tenant_id AND m.user_id = actor AND m.is_active
                     AND m.role IN ('owner', 'administrator')) THEN
            RETURN NEW;
        END IF;
        IF NEW.user_id = actor
           AND EXISTS (SELECT 1 FROM tenants_tenantinvitation i
                       WHERE i.tenant_id = NEW.tenant_id AND i.accepted_by_id = actor
                         AND i.role = NEW.role) THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'membership insert not authorised' USING ERRCODE = '42501';
    END $$;
    CREATE TRIGGER membership_insert_guard BEFORE INSERT ON tenants_tenantmembership
        FOR EACH ROW EXECUTE FUNCTION app.check_membership_insert();
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_app_schema"),
        ("accounts", "0001_initial"),
        ("tenants", "0001_initial"),
    ]

    operations = [
        EnableRLS("tenants_tenantmembership"),
        migrations.RunSQL(MEMBERSHIP_POLICIES, migrations.RunSQL.noop),
        EnableRLS("tenants_tenant"),
        migrations.RunSQL(TENANT_POLICIES, migrations.RunSQL.noop),
        EnableRLS("accounts_user"),
        migrations.RunSQL(USER_POLICIES, migrations.RunSQL.noop),
        EnableRLS("tenants_tenantinvitation"),
        migrations.RunSQL(INVITATION_POLICIES, migrations.RunSQL.noop),
        EnableTenantRLS("tenants_tenantsettings"),
        EnableTenantRLS("tenants_companyfiscalprofile"),
        migrations.RunSQL(MEMBERSHIP_TRIGGER, migrations.RunSQL.noop),
    ]
