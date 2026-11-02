from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

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
