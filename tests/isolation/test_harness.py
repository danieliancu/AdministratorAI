import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import connection

from apps.core.db.guard import check_role_on_connect
from apps.core.db.scope import db_scope
from apps.tenants.models import Tenant
from tests.factories import make_tenant, make_user


@pytest.mark.django_db
def test_tests_run_as_the_restricted_role():
    with db_scope(), connection.cursor() as cursor:
        cursor.execute("SELECT current_user, session_user")
        assert cursor.fetchone() == ("aai_app", "aai_app")


@pytest.mark.django_db
def test_role_guard_accepts_the_restricted_role():
    with db_scope():
        check_role_on_connect(None, connection)


def test_negative_control_rls_is_what_hides_the_rows(committed_db, owner_connection):
    """If the row were not visible with RLS off, the isolation suite would prove nothing."""
    tenant = make_tenant(make_user())
    count_sql = "SELECT count(*) FROM tenants_tenantmembership WHERE tenant_id = %s"

    with db_scope():
        assert not Tenant.objects.filter(pk=tenant.pk).exists()
    # FORCE RLS applies to the table owner as well.
    assert owner_connection.execute(count_sql, [tenant.pk]).fetchone()[0] == 0

    owner_connection.execute("ALTER TABLE tenants_tenantmembership NO FORCE ROW LEVEL SECURITY")
    assert owner_connection.execute(count_sql, [tenant.pk]).fetchone()[0] == 1
    owner_connection.rollback()


def test_role_guard_refuses_the_owner(owner_connection, settings):
    settings.AAI_DB_ROLE_GUARD = True

    class FakeCursor:
        def __enter__(self):
            return owner_connection.cursor()

        def __exit__(self, *exc):
            return False

    class FakeConnection:
        vendor = "postgresql"

        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    with pytest.raises(ImproperlyConfigured, match="owns"):
        check_role_on_connect(None, FakeConnection())
