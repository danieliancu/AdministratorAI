"""Read the Postgres catalog, not the Django models, so tables without a model are caught too."""

import pytest
from django.apps import apps

from apps.core.db import manifest


def _rows(conn, sql):
    return conn.execute(sql).fetchall()


def test_every_public_table_is_classified(owner_connection):
    tables = {
        row[0]
        for row in _rows(
            owner_connection,
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'",
        )
    }
    assert tables == manifest.ALL_TABLES


def test_protected_tables_force_rls(owner_connection):
    rows = _rows(
        owner_connection,
        """SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity FROM pg_class c
           JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')""",
    )
    state = {name: (enabled, forced) for name, enabled, forced in rows}
    for table in manifest.RLS_TABLES | manifest.AUDIT:
        assert state[table] == (True, True), table


def test_every_table_with_tenant_id_is_protected(owner_connection):
    tables = {
        row[0]
        for row in _rows(
            owner_connection,
            """SELECT table_name FROM information_schema.columns
               WHERE table_schema = 'public' AND column_name = 'tenant_id'""",
        )
    }
    assert tables == manifest.TENANT | {"audit_tenantevent"}


def test_policies_cover_each_command_separately(owner_connection):
    rows = _rows(
        owner_connection,
        "SELECT tablename, cmd, qual, with_check FROM pg_policies WHERE schemaname = 'public'",
    )
    commands = {}
    for table, cmd, qual, with_check in rows:
        assert cmd != "ALL", f"{table} uses FOR ALL"
        commands.setdefault(table, set()).add(cmd)
        if cmd in ("SELECT", "DELETE"):
            assert qual is not None, table
        if cmd == "INSERT":
            assert with_check is not None, table
        if cmd == "UPDATE":
            assert qual is not None and with_check is not None, table
    for table in manifest.TENANT:
        assert commands[table] == {"SELECT", "INSERT", "UPDATE", "DELETE"}, table
    assert commands["tenants_tenant"] == {"SELECT", "INSERT", "UPDATE"}
    assert commands["accounts_user"] == {"SELECT", "INSERT", "UPDATE"}


def test_unconditional_policies_never_apply_to_the_runtime_roles(owner_connection):
    rows = _rows(
        owner_connection,
        """SELECT policyname, roles FROM pg_policies
           WHERE schemaname = 'public' AND qual = 'true'""",
    )
    assert rows
    for name, roles in rows:
        assert "aai_app" not in roles and "aai_platform" not in roles, name


def test_platform_role_has_no_direct_table_access(owner_connection):
    rows = _rows(
        owner_connection,
        """SELECT table_schema, table_name FROM information_schema.role_table_grants
           WHERE grantee = 'aai_platform' AND table_schema <> 'platform'""",
    )
    assert rows == []


def test_app_role_cannot_use_the_platform_schema(owner_connection):
    rows = _rows(owner_connection, "SELECT has_schema_privilege('aai_app', 'platform', 'USAGE')")
    assert rows == [(False,)]


def test_platform_functions_are_not_public(owner_connection):
    rows = _rows(
        owner_connection,
        """SELECT p.proname, p.prosecdef, p.proconfig IS NOT NULL,
                  has_function_privilege('aai_app', p.oid, 'EXECUTE')
           FROM pg_proc p WHERE p.pronamespace = 'platform'::regnamespace""",
    )
    assert rows
    for name, _definer, has_config, app_can_execute in rows:
        assert has_config, f"{name} must pin its search_path"
        assert not app_can_execute, name


def test_only_platform_functions_are_security_definer(owner_connection):
    rows = _rows(
        owner_connection,
        """SELECT n.nspname, p.proname FROM pg_proc p
           JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE p.prosecdef AND n.nspname NOT LIKE 'pg\\_%'""",
    )
    assert {row[0] for row in rows} == {"platform"}


def test_definer_cannot_read_password_hashes(owner_connection):
    rows = _rows(
        owner_connection,
        """SELECT has_column_privilege('aai_platform_definer', 'accounts_user', 'password',
                                       'SELECT'),
                  has_column_privilege('aai_platform', 'accounts_user', 'password', 'SELECT')""",
    )
    assert rows == [(False, False)]


def test_app_role_has_no_dangerous_privileges(owner_connection):
    rows = _rows(
        owner_connection,
        """SELECT table_name, privilege_type FROM information_schema.role_table_grants
           WHERE grantee = 'aai_app' AND privilege_type IN ('TRUNCATE', 'REFERENCES', 'TRIGGER')""",
    )
    assert rows == []


def test_app_role_cannot_change_tenant_status(owner_connection):
    rows = _rows(
        owner_connection,
        """SELECT has_column_privilege('aai_app', 'tenants_tenant', 'status', 'UPDATE'),
                  has_column_privilege('aai_app', 'tenants_tenant', 'name', 'UPDATE')""",
    )
    assert rows == [(False, True)]


def test_unique_constraints_include_tenant_or_are_allowlisted(owner_connection):
    rows = _rows(
        owner_connection,
        """SELECT c.conrelid::regclass::text,
                  string_agg(a.attname, ',' ORDER BY a.attname)
           FROM pg_constraint c
           CROSS JOIN LATERAL unnest(c.conkey) AS k(attnum)
           JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
           WHERE c.contype = 'u' AND c.connamespace = 'public'::regnamespace
           GROUP BY c.conrelid, c.oid""",
    )
    for table, columns in rows:
        if table not in manifest.RLS_TABLES or "tenant_id" in columns.split(","):
            continue
        assert columns in manifest.UNIQUE_WITHOUT_TENANT.get(table, set()), (table, columns)


def test_tenant_to_tenant_foreign_keys_are_composite(owner_connection):
    rows = _rows(
        owner_connection,
        """SELECT c.conrelid::regclass::text, c.confrelid::regclass::text, cardinality(c.conkey)
           FROM pg_constraint c
           WHERE c.contype = 'f' AND c.connamespace = 'public'::regnamespace""",
    )
    for source, target, columns in rows:
        if source in manifest.TENANT and target in manifest.TENANT:
            assert columns == 2, (source, target)


@pytest.mark.django_db
def test_models_and_manifest_agree():
    model_tables = {model._meta.db_table for model in apps.get_models()}
    assert model_tables <= manifest.ALL_TABLES


def test_application_cannot_reach_platform_only_tables(owner_connection):
    for table in manifest.PLATFORM_ONLY:
        rows = _rows(
            owner_connection, f"SELECT has_table_privilege('aai_app', '{table}', 'SELECT')"
        )
        assert rows == [(False,)], table


def test_application_only_reads_the_global_catalog(owner_connection):
    for table in manifest.GLOBAL_REF:
        rows = _rows(
            owner_connection,
            f"""SELECT has_table_privilege('aai_app', '{table}', 'SELECT'),
                       has_table_privilege('aai_app', '{table}', 'INSERT'),
                       has_table_privilege('aai_app', '{table}', 'UPDATE'),
                       has_table_privilege('aai_app', '{table}', 'DELETE')""",
        )
        assert rows == [(True, False, False, False)], table
