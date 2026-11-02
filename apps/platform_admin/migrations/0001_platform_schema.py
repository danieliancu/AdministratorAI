from django.db import migrations

ROLE = "aai_platform_definer"

# The definer role owns the views and functions below. It gets only what they need,
# and accounts_user deliberately excludes the password column.
DEFINER_ACCESS = f"""
    GRANT USAGE ON SCHEMA app TO {ROLE};

    GRANT SELECT, INSERT ON tenants_tenant TO {ROLE};
    GRANT UPDATE (status) ON tenants_tenant TO {ROLE};
    CREATE POLICY tenant_sel_platform ON tenants_tenant FOR SELECT TO {ROLE} USING (true);
    CREATE POLICY tenant_ins_platform ON tenants_tenant FOR INSERT TO {ROLE} WITH CHECK (true);
    CREATE POLICY tenant_upd_platform ON tenants_tenant FOR UPDATE TO {ROLE}
        USING (true) WITH CHECK (true);

    GRANT SELECT, INSERT ON tenants_tenantmembership TO {ROLE};
    CREATE POLICY membership_sel_platform ON tenants_tenantmembership FOR SELECT TO {ROLE}
        USING (true);
    CREATE POLICY membership_ins_platform ON tenants_tenantmembership FOR INSERT TO {ROLE}
        WITH CHECK (true);

    GRANT INSERT ON tenants_tenantsettings TO {ROLE};
    CREATE POLICY settings_ins_platform ON tenants_tenantsettings FOR INSERT TO {ROLE}
        WITH CHECK (true);
    GRANT INSERT ON tenants_companyfiscalprofile TO {ROLE};
    CREATE POLICY fiscal_ins_platform ON tenants_companyfiscalprofile FOR INSERT TO {ROLE}
        WITH CHECK (true);

    GRANT SELECT (id, email, is_active, email_verified_at, created_at) ON accounts_user TO {ROLE};
    CREATE POLICY user_sel_platform ON accounts_user FOR SELECT TO {ROLE} USING (true);

    GRANT INSERT ON audit_tenantevent TO {ROLE};
    CREATE POLICY tenantevent_ins_platform ON audit_tenantevent FOR INSERT TO {ROLE}
        WITH CHECK (true);
    GRANT SELECT ON audit_securityevent TO {ROLE};
    CREATE POLICY securityevent_sel_platform ON audit_securityevent FOR SELECT TO {ROLE}
        USING (true);
    GRANT SELECT, INSERT ON audit_platformevent TO {ROLE};
    CREATE POLICY platformevent_sel_platform ON audit_platformevent FOR SELECT TO {ROLE}
        USING (true);
    CREATE POLICY platformevent_ins_platform ON audit_platformevent FOR INSERT TO {ROLE}
        WITH CHECK (true);
"""

# The grant table: the runtime role reads its own row, and only the owner can write,
# so no application bug can promote anyone to platform staff.
GRANT_TABLE = f"""
    ALTER TABLE accounts_platformgrant ENABLE ROW LEVEL SECURITY;
    ALTER TABLE accounts_platformgrant FORCE ROW LEVEL SECURITY;
    CREATE POLICY grant_sel ON accounts_platformgrant FOR SELECT TO aai_app
        USING (user_id = (SELECT app.current_user_id()));
    GRANT SELECT ON accounts_platformgrant TO aai_app;
    CREATE POLICY grant_sel_owner ON accounts_platformgrant FOR SELECT TO aai_owner USING (true);
    CREATE POLICY grant_ins_owner ON accounts_platformgrant FOR INSERT TO aai_owner
        WITH CHECK (true);
    CREATE POLICY grant_upd_owner ON accounts_platformgrant FOR UPDATE TO aai_owner
        USING (true) WITH CHECK (true);
    CREATE POLICY grant_del_owner ON accounts_platformgrant FOR DELETE TO aai_owner USING (true);
    GRANT SELECT ON accounts_platformgrant TO {ROLE};
    CREATE POLICY grant_sel_platform ON accounts_platformgrant FOR SELECT TO {ROLE} USING (true);
"""

# The definer branch comes first: its functions run with an empty search_path,
# and platform.create_tenant writes its own audit trail.
MEMBERSHIP_TRIGGER = """
    CREATE OR REPLACE FUNCTION app.check_membership_insert() RETURNS trigger
    LANGUAGE plpgsql AS $$
    DECLARE
        actor uuid := app.current_user_id();
    BEGIN
        IF current_user = 'aai_platform_definer' THEN
            RETURN NEW;
        END IF;
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
"""

DEFINER_ATTRS = "LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp"

# Reads are masked at the source, so unmasked data never reaches the process.
PLATFORM_OBJECTS = f"""
    SET LOCAL ROLE {ROLE};

    CREATE FUNCTION platform.mask_email(value text) RETURNS text
    LANGUAGE sql IMMUTABLE SET search_path = pg_catalog, pg_temp AS $$
        SELECT left(value, 1) || '***'
            || CASE WHEN position('@' IN value) > 0
                    THEN '@' || split_part(value, '@', 2) ELSE '' END
    $$;

    CREATE VIEW platform.tenant_overview WITH (security_barrier) AS
        SELECT t.id, t.name, t.status, t.created_at,
               platform.mask_email(u.email) AS creator_email,
               (SELECT count(*) FROM public.tenants_tenantmembership m
                WHERE m.tenant_id = t.id AND m.is_active) AS member_count
        FROM public.tenants_tenant t
        JOIN public.accounts_user u ON u.id = t.created_by_id;

    CREATE VIEW platform.user_overview WITH (security_barrier) AS
        SELECT u.id, platform.mask_email(u.email) AS email, u.is_active,
               u.email_verified_at IS NOT NULL AS is_verified, u.created_at,
               (SELECT count(*) FROM public.tenants_tenantmembership m
                WHERE m.user_id = u.id AND m.is_active) AS tenant_count,
               g.role AS platform_role
        FROM public.accounts_user u
        LEFT JOIN public.accounts_platformgrant g ON g.user_id = u.id;

    CREATE VIEW platform.audit_log WITH (security_barrier) AS
        SELECT e.id, e.occurred_at, e.actor_user_id,
               platform.mask_email(u.email) AS actor_email,
               e.action, e.target_tenant_id, t.name AS target_tenant_name, e.reason
        FROM public.audit_platformevent e
        LEFT JOIN public.accounts_user u ON u.id = e.actor_user_id
        LEFT JOIN public.tenants_tenant t ON t.id = e.target_tenant_id;

    CREATE VIEW platform.counts WITH (security_barrier) AS
        SELECT
            (SELECT count(*) FROM public.tenants_tenant) AS tenants_total,
            (SELECT count(*) FROM public.tenants_tenant WHERE status = 'active') AS tenants_active,
            (SELECT count(*) FROM public.tenants_tenant WHERE status = 'suspended')
                AS tenants_suspended,
            (SELECT count(*) FROM public.accounts_user WHERE is_active) AS users_active,
            (SELECT count(*) FROM public.audit_securityevent
             WHERE action = 'login.failed'
               AND occurred_at > now() - interval '24 hours') AS failed_logins_24h;

    CREATE FUNCTION platform.require_superadmin(actor uuid) RETURNS void {DEFINER_ATTRS} AS $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM public.accounts_platformgrant g
                       WHERE g.user_id = actor AND g.role = 'superadmin') THEN
            RAISE EXCEPTION 'superadmin required' USING ERRCODE = '42501';
        END IF;
    END $$;

    CREATE FUNCTION platform.require_reason(reason text) RETURNS void {DEFINER_ATTRS} AS $$
    BEGIN
        IF coalesce(btrim(reason), '') = '' THEN
            RAISE EXCEPTION 'a reason is required' USING ERRCODE = '22023';
        END IF;
    END $$;

    CREATE FUNCTION platform.record_event(
        actor uuid, action text, target uuid, reason text, metadata jsonb
    ) RETURNS void {DEFINER_ATTRS} AS $$
    BEGIN
        -- The owner has no staff account: it records the granting of access itself.
        IF session_user <> 'aai_owner' AND NOT EXISTS (
            SELECT 1 FROM public.accounts_platformgrant g WHERE g.user_id = actor
        ) THEN
            RAISE EXCEPTION 'platform staff required' USING ERRCODE = '42501';
        END IF;
        INSERT INTO public.audit_platformevent
            (id, occurred_at, db_role, actor_user_id, action, target_tenant_id, reason, metadata)
        VALUES (gen_random_uuid(), now(), '', actor, action, target,
                coalesce(reason, ''), coalesce(metadata, '{{}}'::jsonb));
    END $$;

    CREATE FUNCTION platform.record_tenant_mirror(
        tenant uuid, actor uuid, action text, reason text
    ) RETURNS void {DEFINER_ATTRS} AS $$
    BEGIN
        -- Customers can see what platform staff did to their account.
        INSERT INTO public.audit_tenantevent
            (id, occurred_at, db_role, tenant_id, actor_user_id, action, metadata)
        VALUES (gen_random_uuid(), now(), '', tenant, actor, action,
                jsonb_build_object('source', 'platform', 'reason', reason));
    END $$;

    CREATE FUNCTION platform.set_tenant_status(
        actor uuid, tenant uuid, new_status text, reason text
    ) RETURNS void {DEFINER_ATTRS} AS $$
    BEGIN
        PERFORM platform.require_superadmin(actor);
        PERFORM platform.require_reason(reason);
        IF new_status NOT IN ('active', 'suspended') THEN
            RAISE EXCEPTION 'unknown status' USING ERRCODE = '22023';
        END IF;
        UPDATE public.tenants_tenant SET status = new_status WHERE id = tenant;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'tenant not found' USING ERRCODE = 'P0002';
        END IF;
        PERFORM platform.record_event(
            actor, 'tenant.status.' || new_status, tenant, reason, NULL);
        PERFORM platform.record_tenant_mirror(
            tenant, actor, 'platform.tenant.status.' || new_status, reason);
    END $$;

    CREATE FUNCTION platform.create_tenant(
        actor uuid, tenant_name text, owner_login text, reason text
    ) RETURNS uuid {DEFINER_ATTRS} AS $$
    DECLARE
        new_owner uuid;
        new_tenant uuid := gen_random_uuid();
    BEGIN
        PERFORM platform.require_superadmin(actor);
        PERFORM platform.require_reason(reason);
        SELECT id INTO new_owner FROM public.accounts_user
            WHERE email = lower(btrim(owner_login));
        IF new_owner IS NULL THEN
            RAISE EXCEPTION 'owner not found' USING ERRCODE = 'P0002';
        END IF;
        INSERT INTO public.tenants_tenant
            (id, name, status, created_by_id, idempotency_key, created_at)
        VALUES (new_tenant, tenant_name, 'active', new_owner, gen_random_uuid(), now());
        INSERT INTO public.tenants_tenantmembership
            (id, tenant_id, user_id, role, is_active, created_at)
        VALUES (gen_random_uuid(), new_tenant, new_owner, 'owner', true, now());
        INSERT INTO public.tenants_tenantsettings (id, tenant_id, locale, timezone)
        VALUES (gen_random_uuid(), new_tenant, 'ro', 'Europe/Bucharest');
        INSERT INTO public.tenants_companyfiscalprofile
            (id, tenant_id, company_name, cui, registration_number, caen_codes,
             fiscal_regime, vat_status, provenance, updated_at)
        VALUES (gen_random_uuid(), new_tenant, '', '', '', '', '', 'unknown', 'none', now());
        PERFORM platform.record_event(actor, 'tenant.created', new_tenant, reason, NULL);
        PERFORM platform.record_tenant_mirror(
            new_tenant, actor, 'platform.tenant.created', reason);
        RETURN new_tenant;
    END $$;

    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA platform FROM PUBLIC;
    GRANT USAGE ON SCHEMA platform TO aai_platform, aai_owner;
    GRANT SELECT ON platform.tenant_overview, platform.user_overview,
        platform.audit_log, platform.counts TO aai_platform;
    -- Unlike tables, functions inside a view are checked against the querying role.
    GRANT EXECUTE ON FUNCTION platform.mask_email(text) TO aai_platform;
    GRANT EXECUTE ON FUNCTION
        platform.record_event(uuid, text, uuid, text, jsonb),
        platform.set_tenant_status(uuid, uuid, text, text),
        platform.create_tenant(uuid, text, text, text)
        TO aai_platform;
    GRANT EXECUTE ON FUNCTION platform.record_event(uuid, text, uuid, text, jsonb) TO aai_owner;

    RESET ROLE;
"""


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0001_app_schema"),
        ("accounts", "0002_platformgrant"),
        ("tenants", "0002_row_level_security"),
        ("audit", "0002_append_only"),
    ]

    operations = [
        migrations.RunSQL(DEFINER_ACCESS, migrations.RunSQL.noop),
        migrations.RunSQL(GRANT_TABLE, migrations.RunSQL.noop),
        migrations.RunSQL(MEMBERSHIP_TRIGGER, migrations.RunSQL.noop),
        migrations.RunSQL(
            f"CREATE SCHEMA platform AUTHORIZATION {ROLE};", "DROP SCHEMA platform CASCADE;"
        ),
        migrations.RunSQL(PLATFORM_OBJECTS, migrations.RunSQL.noop),
    ]
