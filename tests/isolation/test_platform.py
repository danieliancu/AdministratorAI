import uuid

import psycopg
import pytest
from django.db import DatabaseError, ProgrammingError, connection, connections
from django.urls import get_resolver, reverse

from apps.accounts.models import PlatformGrant
from apps.audit.models import PlatformEvent, SecurityEvent, TenantEvent
from apps.core.db.scope import db_scope
from apps.platform_admin import services
from apps.tenants.models import Tenant
from tests.factories import make_tenant, make_user

PASSWORD = "correct-horse-battery"


def grant(owner_connection, user, role="superadmin"):
    owner_connection.execute(
        "INSERT INTO accounts_platformgrant (id, user_id, role, created_at)"
        " VALUES (gen_random_uuid(), %s, %s, now())",
        [user.pk, role],
    )
    owner_connection.commit()


def sign_in(client, user):
    response = client.post(
        reverse("public:login"), {"identifier": user.email, "password": PASSWORD}
    )
    assert response.status_code == 302
    return response


def platform_scalar(sql, params=None):
    with connections["platform"].cursor() as cursor:
        cursor.execute(sql, params or [])
        return cursor.fetchone()[0]


def test_every_platform_route_declares_a_capability():
    resolver = get_resolver().namespace_dict["platform"][1]
    for pattern in resolver.url_patterns:
        assert getattr(pattern.callback, "required_platform_capability", None), pattern


def test_platform_connection_runs_as_the_restricted_role(committed_db):
    assert platform_scalar("SELECT current_user") == "aai_platform"


def test_platform_role_cannot_read_base_tables(committed_db):
    make_tenant(make_user())
    for table in ("tenants_tenant", "accounts_user", "audit_platformevent"):
        with pytest.raises(ProgrammingError):
            platform_scalar(f"SELECT count(*) FROM public.{table}")


def test_app_role_cannot_call_platform_functions(committed_db):
    user = make_user()
    tenant = make_tenant(user)
    with pytest.raises(ProgrammingError), db_scope(tenant_id=tenant.pk, user_id=user.pk):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT platform.set_tenant_status(%s::uuid, %s::uuid, 'active', 'x')",
                [user.pk, tenant.pk],
            )


def test_platform_views_mask_email_at_the_source(committed_db, owner_connection):
    user = make_user("ana.popescu@example.test")
    make_tenant(user, "Masked SRL")
    row = next(r for r in services.users() if r["id"] == user.pk)
    assert row["email"] == "a***@example.test"
    assert "password" not in row
    tenant = next(r for r in services.tenants("Masked") if r["name"] == "Masked SRL")
    assert tenant["creator_email"] == "a***@example.test"


def test_status_change_requires_superadmin(committed_db, owner_connection):
    staff, owner = make_user(), make_user()
    tenant = make_tenant(owner)
    grant(owner_connection, staff, "support")
    with pytest.raises(ProgrammingError, match="superadmin required"):
        services.set_tenant_status(staff.pk, tenant.pk, "suspended", "motiv")


def test_status_change_requires_a_reason(committed_db, owner_connection):
    staff, owner = make_user(), make_user()
    tenant = make_tenant(owner)
    grant(owner_connection, staff)
    with pytest.raises(DatabaseError, match="reason"):
        services.set_tenant_status(staff.pk, tenant.pk, "suspended", "   ")


def test_suspension_is_audited_for_staff_and_visible_to_the_customer(
    committed_db, owner_connection
):
    staff, owner = make_user(), make_user()
    tenant = make_tenant(owner)
    grant(owner_connection, staff)
    services.set_tenant_status(staff.pk, tenant.pk, "suspended", "plată restantă")

    logged = [r for r in services.audit_log() if r["target_tenant_id"] == tenant.pk]
    assert [r["action"] for r in logged] == ["tenant.status.suspended"]
    assert logged[0]["reason"] == "plată restantă"
    assert logged[0]["actor_user_id"] == staff.pk

    with db_scope(tenant_id=tenant.pk, user_id=owner.pk):
        actions = set(TenantEvent.objects.values_list("action", flat=True))
        assert "platform.tenant.status.suspended" in actions
        assert Tenant.objects.get().status == "suspended"


def test_suspended_tenant_is_refused_over_http(committed_db, owner_connection, client):
    staff, owner = make_user(), make_user()
    tenant = make_tenant(owner)
    grant(owner_connection, staff)
    sign_in(client, owner)
    url = reverse("tenant:dashboard", args=[tenant.pk])
    assert client.get(url).status_code == 200
    services.set_tenant_status(staff.pk, tenant.pk, "suspended", "test")
    assert client.get(url).status_code == 403
    services.set_tenant_status(staff.pk, tenant.pk, "active", "test")
    assert client.get(url).status_code == 200


def test_platform_create_tenant_gives_the_owner_access(committed_db, owner_connection, client):
    staff, owner = make_user(), make_user()
    grant(owner_connection, staff)
    tenant_id = services.create_tenant(
        staff.pk, name="Creată de platformă", owner_login=owner.email, reason="onboarding"
    )
    sign_in(client, owner)
    assert client.get(reverse("tenant:dashboard", args=[tenant_id])).status_code == 200
    with db_scope(user_id=staff.pk):
        assert not Tenant.objects.filter(pk=tenant_id).exists()


def test_non_staff_cannot_discover_the_platform_area(committed_db, client):
    user = make_user()
    sign_in(client, user)
    known = client.get(reverse("platform:overview"))
    unknown = client.get("/platform/nu-exista/")
    assert known.status_code == unknown.status_code == 404


def test_anonymous_is_sent_to_login(committed_db, client):
    response = client.get(reverse("platform:overview"))
    assert response.status_code == 302
    assert reverse("public:login") in response["Location"]


def test_support_can_view_but_not_manage(committed_db, owner_connection, client):
    staff, owner = make_user(), make_user()
    tenant = make_tenant(owner)
    grant(owner_connection, staff, "support")
    sign_in(client, staff)
    assert client.get(reverse("platform:overview")).status_code == 200
    assert client.get(reverse("platform:tenants")).status_code == 200
    assert client.get(reverse("platform:audit")).status_code == 200
    assert client.get(reverse("platform:tenant-new")).status_code == 403
    response = client.post(
        reverse("platform:tenant-status", args=[tenant.pk]),
        {"status": "suspended", "reason": "x"},
    )
    assert response.status_code == 403
    with db_scope(tenant_id=tenant.pk, user_id=owner.pk):
        assert Tenant.objects.get().status == "active"


def test_superadmin_flow_over_http(committed_db, owner_connection, client):
    staff, owner = make_user(), make_user()
    tenant = make_tenant(owner, "Firma Vizibilă")
    grant(owner_connection, staff)
    response = sign_in(client, staff)
    assert response["Location"] == reverse("platform:overview")
    assert "Firma Vizibilă" in client.get(reverse("platform:tenants")).content.decode()
    pages = [reverse("platform:overview"), reverse("platform:users"), reverse("platform:audit")]
    for page in pages:
        assert client.get(page).status_code == 200
    client.post(
        reverse("platform:tenant-status", args=[tenant.pk]),
        {"status": "suspended", "reason": "verificare"},
    )
    with db_scope(tenant_id=tenant.pk, user_id=owner.pk):
        assert Tenant.objects.get().status == "suspended"


def test_platform_pages_never_show_full_emails(committed_db, owner_connection, client):
    staff = make_user()
    owner = make_user("secret.owner@example.test")
    make_tenant(owner)
    grant(owner_connection, staff)
    sign_in(client, staff)
    for name in ("platform:tenants", "platform:users", "platform:audit"):
        assert "secret.owner" not in client.get(reverse(name)).content.decode()


def test_runtime_role_cannot_grant_platform_access(committed_db):
    user = make_user()
    with pytest.raises(ProgrammingError), db_scope(user_id=user.pk):
        PlatformGrant.objects.create(user=user, role="superadmin")


def test_a_user_sees_only_their_own_grant(committed_db, owner_connection):
    staff, other = make_user(), make_user()
    grant(owner_connection, staff)
    with db_scope(user_id=other.pk):
        assert PlatformGrant.objects.count() == 0
    with db_scope(user_id=staff.pk):
        assert PlatformGrant.objects.count() == 1


class TestAppendOnly:
    def test_app_role_cannot_change_or_delete_tenant_events(self, committed_db):
        user = make_user()
        tenant = make_tenant(user)
        for sql in ("UPDATE audit_tenantevent SET action = 'x'", "DELETE FROM audit_tenantevent"):
            with pytest.raises(ProgrammingError), db_scope(tenant_id=tenant.pk, user_id=user.pk):
                with connection.cursor() as cursor:
                    cursor.execute(sql)

    def test_app_role_cannot_read_security_or_platform_events(self, committed_db):
        with pytest.raises(ProgrammingError), db_scope():
            list(SecurityEvent.objects.all())
        with pytest.raises(ProgrammingError), db_scope():
            list(PlatformEvent.objects.all())

    def test_tenant_events_are_isolated(self, committed_db):
        alice, bob = make_user(), make_user()
        tenant_a, tenant_b = make_tenant(alice), make_tenant(bob)
        with db_scope(tenant_id=tenant_b.pk, user_id=bob.pk):
            TenantEvent.objects.create(tenant_id=tenant_b.pk, action="in.b")
        with db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
            TenantEvent.objects.create(tenant_id=tenant_a.pk, action="in.a")
            assert list(TenantEvent.objects.values_list("action", flat=True)) == ["in.a"]
        with pytest.raises(ProgrammingError), db_scope(tenant_id=tenant_a.pk, user_id=alice.pk):
            TenantEvent.objects.create(tenant_id=tenant_b.pk, action="plantat")

    def test_database_stamps_time_and_role(self, committed_db):
        user = make_user()
        tenant = make_tenant(user)
        with db_scope(tenant_id=tenant.pk, user_id=user.pk):
            event = TenantEvent.objects.create(
                tenant_id=tenant.pk, action="x", db_role="falsificat"
            )
            stored = TenantEvent.objects.get(pk=event.pk)
        assert stored.db_role == "aai_app"
        assert stored.occurred_at != event.occurred_at

    @pytest.mark.parametrize(
        "sql",
        ["TRUNCATE audit_platformevent", "TRUNCATE audit_tenantevent"],
    )
    def test_even_the_owner_cannot_truncate(self, committed_db, owner_connection, sql):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            owner_connection.execute(sql)

    def test_owner_update_and_delete_touch_nothing(self, committed_db, owner_connection):
        staff, owner = make_user(), make_user()
        tenant = make_tenant(owner)
        grant(owner_connection, staff)
        services.set_tenant_status(staff.pk, tenant.pk, "suspended", "motiv")
        for sql in ("UPDATE audit_platformevent SET reason = 'x'",
                    "DELETE FROM audit_platformevent"):
            assert owner_connection.execute(sql).rowcount == 0
        assert any(r["reason"] == "motiv" for r in services.audit_log())


def test_failed_login_is_counted_and_stores_only_a_hash(committed_db, owner_connection, client):
    user = make_user()
    before = platform_scalar("SELECT failed_logins_24h FROM platform.counts")
    client.post(reverse("public:login"), {"identifier": user.email, "password": "gresit"})
    assert platform_scalar("SELECT failed_logins_24h FROM platform.counts") == before + 1
    columns = {
        row[0]
        for row in owner_connection.execute(
            """SELECT column_name FROM information_schema.columns
               WHERE table_name = 'audit_securityevent'"""
        ).fetchall()
    }
    assert "identifier_hash" in columns
    assert not {"email", "identifier", "password"} & columns


def test_unknown_tenant_status_change_fails_cleanly(committed_db, owner_connection):
    staff = make_user()
    grant(owner_connection, staff)
    with pytest.raises(DatabaseError, match="tenant not found"):
        services.set_tenant_status(staff.pk, uuid.uuid4(), "suspended", "motiv")
