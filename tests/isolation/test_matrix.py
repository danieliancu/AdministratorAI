"""Every tenant-owned table, under every kind of access: read, modify, export, discover."""

import threading
import uuid
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import DatabaseError, connection, connections
from django.db.models import Count
from django.utils import timezone

from apps.audit.models import TenantEvent
from apps.core.db.scope import db_scope
from apps.tenants import services
from apps.tenants.models import (
    CompanyFiscalProfile,
    TenantInvitation,
    TenantMembership,
    TenantSettings,
)
from apps.tenants.roles import Role
from tests.factories import make_tenant, make_user


def _membership(tenant, user):
    return TenantMembership.objects.get(tenant=tenant, user=user)


def _make_settings(tenant, user):
    return TenantSettings.objects.create(tenant=tenant)


def _make_profile(tenant, user):
    return CompanyFiscalProfile.objects.create(tenant=tenant, company_name="Secret")


def _make_invitation(tenant, user):
    return TenantInvitation.objects.create(
        tenant=tenant,
        email="x@example.test",
        role=Role.MEMBER,
        token_hash=uuid.uuid4().hex,
        invited_by=_membership(tenant, user),
        expires_at=timezone.now() + timedelta(days=1),
    )


MODELS = [
    pytest.param(TenantMembership, _membership, id="membership"),
    pytest.param(TenantSettings, _make_settings, id="settings"),
    pytest.param(CompanyFiscalProfile, _make_profile, id="fiscal-profile"),
    pytest.param(TenantInvitation, _make_invitation, id="invitation"),
]


@pytest.fixture
def world():
    alice, bob = make_user(), make_user()
    return alice, bob, make_tenant(alice), make_tenant(bob)


def _foreign_row(world, make):
    alice, bob, tenant_a, tenant_b = world
    with db_scope(tenant_id=tenant_b.pk, user_id=bob.pk):
        return make(tenant_b, bob)


@pytest.mark.django_db
@pytest.mark.parametrize("model,make", MODELS)
class TestEveryTenantModel:
    def test_read(self, world, model, make):
        alice, bob, tenant_a, tenant_b = world
        row = _foreign_row(world, make)
        with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
            assert not model.objects.filter(pk=row.pk).exists()
            assert not model.objects.filter(tenant_id=tenant_b.pk).exists()
            aggregate = model.objects.filter(tenant_id=tenant_b.pk).aggregate(n=Count("pk"))
            assert aggregate["n"] == 0

    def test_raw_read_and_join(self, world, model, make):
        alice, bob, tenant_a, tenant_b = world
        row = _foreign_row(world, make)
        table = model._meta.db_table
        with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk), connection.cursor() as cursor:
            cursor.execute(f"SELECT id FROM {table} WHERE id = %s", [row.pk])
            assert cursor.fetchall() == []
            cursor.execute(
                f"SELECT x.id FROM {table} x JOIN tenants_tenant t ON t.id = x.tenant_id"
                " WHERE x.tenant_id = %s",
                [tenant_b.pk],
            )
            assert cursor.fetchall() == []

    def test_update_and_delete_reach_nothing(self, world, model, make):
        alice, bob, tenant_a, tenant_b = world
        row = _foreign_row(world, make)
        with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
            assert model.objects.filter(pk=row.pk).update(tenant_id=tenant_a.pk) == 0
            assert model.objects.filter(pk=row.pk).delete()[0] == 0
        with db_scope(tenant_id=tenant_b.pk, user_id=bob.pk):
            assert model.objects.filter(pk=row.pk).exists()

    def test_copy_export(self, world, model, make):
        alice, bob, tenant_a, tenant_b = world
        row = _foreign_row(world, make)
        table = model._meta.db_table
        with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk), connection.cursor() as cursor:
            with cursor.copy(f"COPY (SELECT * FROM {table}) TO STDOUT") as copy:
                exported = b"".join(bytes(chunk) for chunk in copy)
        assert str(row.pk).encode() not in exported

    def test_dumpdata_export(self, world, model, make, tmp_path):
        alice, bob, tenant_a, tenant_b = world
        row = _foreign_row(world, make)
        output = tmp_path / "dump.json"
        with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
            call_command("dumpdata", model._meta.label, output=str(output), verbosity=0)
        assert str(row.pk) not in output.read_text()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "table,columns",
    [
        ("tenants_tenantsettings", "id, tenant_id, locale, timezone"),
        (
            "tenants_companyfiscalprofile",
            "id, tenant_id, company_name, cui, registration_number, caen_codes,"
            " fiscal_regime, vat_status, provenance, updated_at",
        ),
    ],
)
def test_raw_insert_into_a_foreign_tenant_is_refused(world, table, columns):
    alice, bob, tenant_a, tenant_b = world
    placeholders = {
        "tenants_tenantsettings": "%s, %s, 'ro', 'UTC'",
        "tenants_companyfiscalprofile": "%s, %s, '', '', '', '', '', 'unknown', 'none', now()",
    }[table]
    with pytest.raises(DatabaseError), db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                [uuid.uuid4(), tenant_b.pk],
            )


def _in_thread(function):
    errors = []

    def runner():
        try:
            function()
        except Exception as exc:
            errors.append(exc)
        finally:
            connections.close_all()

    thread = threading.Thread(target=runner)
    return thread, errors


def test_two_tenants_at_once_never_see_each_other(committed_db):
    alice, bob = make_user(), make_user()
    tenant_a, tenant_b = make_tenant(alice), make_tenant(bob)
    barrier = threading.Barrier(2, timeout=20)

    def worker(tenant, user):
        def run():
            for _ in range(25):
                with db_scope(tenant_id=tenant.pk, user_id=user.pk):
                    barrier.wait()
                    seen = set(TenantMembership.objects.values_list("tenant_id", flat=True))
                    assert seen == {tenant.pk}
                    barrier.wait()

        return run

    threads = [_in_thread(worker(tenant_a, alice)), _in_thread(worker(tenant_b, bob))]
    for thread, _ in threads:
        thread.start()
    for thread, _ in threads:
        thread.join(60)
    assert [errors for _, errors in threads] == [[], []]


def test_double_submit_creates_a_single_tenant(committed_db):
    user = make_user()
    key = uuid.uuid4()
    results = []

    def create():
        results.append(services.create_tenant(user, name="Dublu", idempotency_key=key).pk)

    threads = [_in_thread(create) for _ in range(4)]
    for thread, _ in threads:
        thread.start()
    for thread, _ in threads:
        thread.join(60)
    assert [errors for _, errors in threads] == [[], [], [], []]
    assert len(results) == 4 and len(set(results)) == 1
    with db_scope(user_id=user.pk):
        assert TenantMembership.objects.count() == 1


def test_concurrent_requests_cannot_pass_the_tenant_quota(committed_db, monkeypatch):
    monkeypatch.setattr(services, "MAX_TENANTS_PER_USER", 2)
    user = make_user()

    def create():
        services.create_tenant(user, name="Cotă", idempotency_key=uuid.uuid4())

    threads = [_in_thread(create) for _ in range(5)]
    for thread, _ in threads:
        thread.start()
    for thread, _ in threads:
        thread.join(60)
    failures = [e for _, errors in threads for e in errors]
    assert len(failures) == 3
    assert all(isinstance(e, services.QuotaExceeded) for e in failures)
    with db_scope(user_id=user.pk):
        assert TenantMembership.objects.count() == 2


def test_an_invitation_token_works_only_once_under_concurrency(committed_db):
    alice, bob = make_user(), make_user()
    tenant = make_tenant(alice)
    with db_scope(tenant_id=tenant.pk, user_id=alice.pk):
        token = services.invite_member(
            tenant_id=tenant.pk,
            invited_by_membership_id=_membership(tenant, alice).pk,
            email=bob.email,
            role=Role.MEMBER,
        )

    def accept():
        services.accept_invitation(bob, token)

    threads = [_in_thread(accept) for _ in range(3)]
    for thread, _ in threads:
        thread.start()
    for thread, _ in threads:
        thread.join(60)
    failures = [e for _, errors in threads for e in errors]
    assert len(failures) == 2
    assert all(isinstance(e, services.InvitationInvalid) for e in failures)
    with db_scope(tenant_id=tenant.pk, user_id=alice.pk):
        assert TenantMembership.objects.filter(user=bob).count() == 1
        assert TenantEvent.objects.filter(action="member.joined").count() == 1
