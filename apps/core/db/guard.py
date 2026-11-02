import re

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .scope import UnscopedQuery, current_scope

ROLE_FACTS_SQL = """
SELECT r.rolsuper,
       r.rolbypassrls,
       r.rolcreaterole,
       r.rolcreatedb,
       EXISTS (
           SELECT FROM pg_class c
           JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE c.relowner = r.oid
             AND n.nspname NOT IN ('pg_catalog', 'information_schema')
             AND n.nspname NOT LIKE 'pg\\_%'
       ) AS owns_relations,
       EXISTS (SELECT FROM pg_auth_members m WHERE m.member = r.oid) AS has_memberships,
       EXISTS (
           SELECT FROM pg_database d
           WHERE d.datname = current_database() AND d.datdba = r.oid
       ) AS owns_database
FROM pg_roles r
WHERE r.rolname = current_user
"""

FACT_NAMES = (
    "superuser",
    "bypassrls",
    "createrole",
    "createdb",
    "owns relations",
    "has role memberships",
    "owns database",
)

# Statements allowed outside a db_scope: transaction control, the scope itself,
# the health probe, and the few tables that hold no tenant data.
UNSCOPED_ALLOWED = re.compile(
    r"""^\s*(
        SAVEPOINT\b | RELEASE\b | ROLLBACK\b | SET\s+CONSTRAINTS\b
        | SELECT\s+set_config\( | SELECT\s+1\s*$
        | .*"django_session"
        | .*"django_content_type"
        | .*"auth_permission"
        | .*"django_migrations"
        | .*pg_catalog\.pg_class\b
    )""",
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


def role_violations(facts):
    return [name for name, present in zip(FACT_NAMES, facts, strict=True) if present]


def check_role_on_connect(sender, connection, **kwargs):
    if not settings.AAI_DB_ROLE_GUARD or connection.vendor != "postgresql":
        return
    with connection.cursor() as cursor:
        cursor.execute(ROLE_FACTS_SQL)
        facts = cursor.fetchone()
    violations = role_violations(facts)
    if violations:
        connection.close()
        raise ImproperlyConfigured(
            f"Database role is not safe for runtime use: {', '.join(violations)}"
        )


def query_guard(execute, sql, params, many, context):
    if (
        settings.AAI_DB_ROLE_GUARD
        and current_scope() is None
        and sql != ROLE_FACTS_SQL
        and not UNSCOPED_ALLOWED.match(str(sql))
    ):
        raise UnscopedQuery(f"Query outside db_scope: {str(sql)[:120]}")
    return execute(sql, params, many, context)


def install_query_guard(sender, connection, **kwargs):
    if connection.alias == "default" and query_guard not in connection.execute_wrappers:
        connection.execute_wrappers.append(query_guard)
