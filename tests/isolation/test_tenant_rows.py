import uuid
from datetime import timedelta

import pytest
from django.db import DatabaseError, IntegrityError, ProgrammingError, connection
from django.utils import timezone

from apps.accounts.models import User
from apps.core.db.scope import db_scope
from apps.tenants.models import (
    CompanyFiscalProfile,
    Tenant,
    TenantInvitation,
    TenantMembership,
)
from apps.tenants.roles import Role
from tests.factories import make_tenant, make_user

pytestmark = pytest.mark.django_db


@pytest.fixture
def world():
    alice, bob = make_user(), make_user()
    tenant_a, tenant_b = make_tenant(alice, "A"), make_tenant(bob, "B")
    with db_scope(tenant_id=tenant_b.pk, user_id=bob.pk):
        CompanyFiscalProfile.objects.create(tenant=tenant_b, company_name="Secret B")
    return alice, bob, tenant_a, tenant_b


def test_read_is_limited_to_the_current_tenant(world):
    alice, bob, tenant_a, tenant_b = world
    with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
        assert list(Tenant.objects.values_list("name", flat=True)) == ["A"]
        assert CompanyFiscalProfile.objects.count() == 0
        assert not TenantMembership.objects.filter(tenant_id=tenant_b.pk).exists()


def test_raw_sql_without_a_filter_is_limited_too(world):
    alice, bob, tenant_a, tenant_b = world
    with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk), connection.cursor() as cursor:
        cursor.execute("SELECT tenant_id FROM tenants_tenantmembership")
        assert {row[0] for row in cursor.fetchall()} == {tenant_a.pk}


def test_update_and_delete_cannot_reach_another_tenant(world):
    alice, bob, tenant_a, tenant_b = world
    with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
        assert TenantMembership.objects.filter(tenant_id=tenant_b.pk).update(role="member") == 0
        assert CompanyFiscalProfile.objects.filter(tenant_id=tenant_b.pk).delete()[0] == 0
    with db_scope(tenant_id=tenant_b.pk, user_id=bob.pk):
        assert TenantMembership.objects.get(user=bob).role == Role.OWNER
        assert CompanyFiscalProfile.objects.count() == 1


def test_insert_into_another_tenant_is_refused(world):
    alice, bob, tenant_a, tenant_b = world
    with pytest.raises(ProgrammingError), db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
        CompanyFiscalProfile.objects.create(tenant_id=tenant_b.pk, company_name="Plantat")


def test_a_row_cannot_be_moved_to_another_tenant(world):
    alice, bob, tenant_a, tenant_b = world
    with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
        CompanyFiscalProfile.objects.create(tenant=tenant_a, company_name="A")
    with pytest.raises(DatabaseError), db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
        CompanyFiscalProfile.objects.filter(tenant=tenant_a).update(tenant_id=tenant_b.pk)


def test_copy_export_only_returns_the_current_tenant(world):
    alice, bob, tenant_a, tenant_b = world
    with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk), connection.cursor() as cursor:
        with cursor.copy("COPY (SELECT tenant_id FROM tenants_tenantmembership) TO STDOUT") as copy:
            exported = b"".join(bytes(chunk) for chunk in copy)
    assert str(tenant_a.pk).encode() in exported
    assert str(tenant_b.pk).encode() not in exported


def test_foreign_key_probe_cannot_tell_a_foreign_id_from_a_missing_one(world):
    alice, bob, tenant_a, tenant_b = world
    with db_scope(tenant_id=tenant_b.pk, user_id=bob.pk):
        foreign_membership = TenantMembership.objects.get(user=bob).pk

    errors = []
    for candidate in (foreign_membership, uuid.uuid4()):
        with pytest.raises(IntegrityError) as caught:
            with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
                TenantInvitation.objects.create(
                    tenant=tenant_a,
                    email="x@example.test",
                    role=Role.MEMBER,
                    token_hash=uuid.uuid4().hex,
                    invited_by_id=candidate,
                    expires_at=timezone.now() + timedelta(days=1),
                )
                connection.check_constraints()
        errors.append(type(caught.value))
    assert errors[0] is errors[1]


def test_identity_mode_lists_my_tenants_only(world):
    alice, bob, tenant_a, tenant_b = world
    with db_scope(user_id=alice.pk):
        assert list(Tenant.objects.values_list("pk", flat=True)) == [tenant_a.pk]
        assert list(TenantMembership.objects.values_list("tenant_id", flat=True)) == [tenant_a.pk]


def test_my_rows_in_tenant_b_do_not_appear_inside_tenant_a(world):
    alice, bob, tenant_a, tenant_b = world
    with db_scope(tenant_id=tenant_a.pk, user_id=bob.pk):
        assert not TenantMembership.objects.filter(user=bob).exists()


def test_users_of_other_tenants_cannot_be_enumerated(world):
    alice, bob, tenant_a, tenant_b = world
    with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
        assert list(User.objects.values_list("pk", flat=True)) == [alice.pk]
    with db_scope():
        assert User.objects.count() == 0
    with db_scope(lookup_email=bob.email):
        assert list(User.objects.values_list("pk", flat=True)) == [bob.pk]


def test_a_user_cannot_edit_another_user(world):
    alice, bob, tenant_a, tenant_b = world
    with db_scope(lookup_email=bob.email, user_id=alice.pk):
        assert User.objects.filter(pk=bob.pk).update(full_name="Hacked") == 0


def test_entering_a_foreign_context_does_not_allow_self_promotion(world):
    alice, bob, tenant_a, tenant_b = world
    with pytest.raises(ProgrammingError, match="not authorised"):
        with db_scope(tenant_id=tenant_b.pk, user_id=alice.pk):
            TenantMembership.objects.create(tenant=tenant_b, user=alice, role=Role.OWNER)


def test_status_cannot_be_changed_by_the_application(world):
    alice, bob, tenant_a, tenant_b = world
    with pytest.raises(ProgrammingError), db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
        Tenant.objects.filter(pk=tenant_a.pk).update(status="active")


def test_tenant_cannot_be_deleted_by_the_application(world):
    alice, bob, tenant_a, tenant_b = world
    with pytest.raises(ProgrammingError), db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM tenants_tenant")


def test_tenant_insert_must_match_context_and_creator(world):
    alice, bob, tenant_a, tenant_b = world
    other = uuid.uuid4()
    with pytest.raises(ProgrammingError), db_scope(tenant_id=uuid.uuid4(), user_id=alice.pk):
        Tenant.objects.create(id=other, name="X", created_by=alice)
