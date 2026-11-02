import uuid

import pytest
from celery import shared_task
from celery.exceptions import Reject
from django.core.exceptions import ImproperlyConfigured

from apps.audit.models import TenantEvent
from apps.core.db.scope import current_scope, db_scope
from apps.core.tasks import ScopedTask, TenantTask, enqueue
from apps.tenants.models import CompanyFiscalProfile, Tenant
from apps.tenants.tasks import record_context_probe
from config.celery import app
from tests.factories import make_tenant, make_user


@shared_task(base=TenantTask, name="tests.read_profiles")
def read_profiles():
    return list(CompanyFiscalProfile.objects.values_list("company_name", flat=True))


@shared_task(base=ScopedTask, name="tests.undeclared")
def undeclared():
    return "ran"


def test_all_project_tasks_declare_a_scope():
    app.loader.import_default_modules()
    for name, task in app.tasks.items():
        if name.startswith("celery.") or name == "tests.undeclared":
            continue
        assert task.scope in ("tenant", "system"), name


def test_a_task_without_a_scope_refuses_to_run():
    with pytest.raises(ImproperlyConfigured):
        undeclared()


def test_tenant_task_without_context_is_rejected():
    with pytest.raises(Reject):
        read_profiles()


def test_task_sees_only_its_tenant(committed_db):
    alice, bob = make_user(), make_user()
    tenant_a, tenant_b = make_tenant(alice), make_tenant(bob)
    with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
        CompanyFiscalProfile.objects.create(tenant=tenant_a, company_name="A")
    with db_scope(tenant_id=tenant_b.pk, user_id=bob.pk):
        CompanyFiscalProfile.objects.create(tenant=tenant_b, company_name="B")
    assert read_profiles(_tenant_id=str(tenant_a.pk), _actor_id=str(alice.pk)) == ["A"]
    assert read_profiles(_tenant_id=str(tenant_b.pk), _actor_id=str(bob.pk)) == ["B"]
    assert current_scope() is None


def test_task_for_a_suspended_or_missing_tenant_does_nothing(committed_db, owner_connection):
    user = make_user()
    tenant = make_tenant(user)
    owner_connection.execute(
        "ALTER TABLE tenants_tenant NO FORCE ROW LEVEL SECURITY"
    )
    owner_connection.execute("UPDATE tenants_tenant SET status = 'suspended' WHERE id = %s",
                             [tenant.pk])
    owner_connection.execute("ALTER TABLE tenants_tenant FORCE ROW LEVEL SECURITY")
    owner_connection.commit()
    assert read_profiles(_tenant_id=str(tenant.pk), _actor_id=str(user.pk)) is None
    assert read_profiles(_tenant_id=str(uuid.uuid4())) is None


def test_enqueue_needs_a_tenant_scope():
    with pytest.raises(ImproperlyConfigured):
        enqueue(read_profiles)


def test_enqueue_sends_only_after_commit_and_carries_context(committed_db, monkeypatch):
    user = make_user()
    tenant = make_tenant(user)
    sent = []
    monkeypatch.setattr(
        read_profiles, "apply_async", lambda args, kwargs: sent.append((args, kwargs))
    )
    with db_scope(tenant_id=tenant.pk, user_id=user.pk):
        enqueue(read_profiles)
        assert sent == []
    assert sent == [((), {"_tenant_id": str(tenant.pk), "_actor_id": str(user.pk)})]


def test_enqueue_through_celerys_real_send_path(committed_db):
    """No patching of apply_async: Celery validates kwargs there, before anything is sent."""
    user = make_user()
    tenant = make_tenant(user)
    previous = app.conf.task_always_eager
    app.conf.task_always_eager = True
    try:
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            enqueue(record_context_probe)
    finally:
        app.conf.task_always_eager = previous
    with db_scope(tenant_id=tenant.pk, user_id=user.pk):
        assert TenantEvent.objects.filter(action="diagnostic.worker_context").count() == 1


def test_rolled_back_transaction_sends_nothing(committed_db, monkeypatch):
    user = make_user()
    tenant = make_tenant(user)
    sent = []
    monkeypatch.setattr(read_profiles, "apply_async", lambda args, kwargs: sent.append(args))
    with pytest.raises(ValueError), db_scope(tenant_id=tenant.pk, user_id=user.pk):
        enqueue(read_profiles)
        raise ValueError
    assert sent == []


def test_context_probe_writes_into_the_right_tenant(committed_db):
    user = make_user()
    tenant = make_tenant(user)
    assert record_context_probe(_tenant_id=str(tenant.pk), _actor_id=str(user.pk)) == str(tenant.pk)
    with db_scope(tenant_id=tenant.pk, user_id=user.pk):
        assert TenantEvent.objects.filter(action="diagnostic.worker_context").count() == 1
        assert Tenant.objects.count() == 1
