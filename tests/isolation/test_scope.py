import uuid

import pytest
from django.db import connection, transaction

from apps.core.db.scope import ScopeViolation, UnscopedQuery, current_scope, db_scope
from apps.tenants.models import Tenant
from tests.factories import make_tenant, make_user


def _setting(name):
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting(%s, true)", [name])
        return cursor.fetchone()[0]


@pytest.mark.django_db
def test_query_without_scope_is_refused():
    with pytest.raises(UnscopedQuery):
        Tenant.objects.count()


@pytest.mark.django_db
def test_empty_scope_sees_nothing():
    make_tenant(make_user())
    with db_scope():
        assert Tenant.objects.count() == 0


@pytest.mark.django_db
def test_scope_restores_the_enclosing_context_on_normal_exit():
    inner = uuid.uuid4()
    user = uuid.uuid4()
    with db_scope(user_id=user):
        with db_scope(tenant_id=inner, user_id=user):
            assert _setting("app.tenant_id") == str(inner)
        assert _setting("app.tenant_id") == ""
        assert _setting("app.user_id") == str(user)


@pytest.mark.django_db
def test_scope_restores_the_enclosing_context_after_an_exception():
    tenant = uuid.uuid4()
    user = uuid.uuid4()
    with db_scope(user_id=user):
        with pytest.raises(ValueError), db_scope(tenant_id=tenant, user_id=user):
            raise ValueError
        assert _setting("app.tenant_id") == ""
        assert current_scope().user_id == user


@pytest.mark.django_db
def test_tenant_scope_cannot_be_replaced_or_left():
    with db_scope(tenant_id=uuid.uuid4()):
        with pytest.raises(ScopeViolation), db_scope(tenant_id=uuid.uuid4()):
            pass
        with pytest.raises(ScopeViolation), db_scope():
            pass


def test_context_does_not_survive_commit_on_a_reused_connection(committed_db):
    tenant = uuid.uuid4()
    with db_scope(tenant_id=tenant):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            pid = cursor.fetchone()[0]

    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SELECT set_config('app.probe', '1', true)")
    with db_scope():
        assert _setting("app.tenant_id") == ""
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            assert cursor.fetchone()[0] == pid
