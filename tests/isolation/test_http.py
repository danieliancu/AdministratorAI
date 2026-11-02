import uuid

import pytest
from django.core import mail
from django.core.exceptions import ImproperlyConfigured
from django.core.management import CommandError, call_command
from django.urls import get_resolver, reverse

from apps.accounts.models import User
from apps.core.db.scope import db_scope
from apps.tenants.models import CompanyFiscalProfile, Tenant, TenantMembership
from apps.tenants.roles import Role
from apps.tenants.services import create_tenant, invite_member
from tests.factories import make_tenant, make_user

pytestmark = pytest.mark.django_db
PASSWORD = "correct-horse-battery"


def sign_in(client, user):
    response = client.post(
        reverse("public:login"), {"identifier": user.email, "password": PASSWORD}
    )
    assert response.status_code == 302
    return response


def test_every_tenant_route_declares_a_capability():
    resolver = get_resolver().namespace_dict["tenant"][1]
    assert resolver.url_patterns
    for pattern in resolver.url_patterns:
        assert getattr(pattern.callback, "required_capability", None), pattern


def test_unnamespaced_route_is_refused(client, settings):
    settings.ROOT_URLCONF = "tests.unscoped_urls"
    with pytest.raises(ImproperlyConfigured):
        client.get("/nescopat/")


def test_anonymous_user_is_sent_to_login(client):
    response = client.get(reverse("tenant:dashboard", args=[uuid.uuid4()]))
    assert response.status_code == 302
    assert reverse("public:login") in response["Location"]


def test_login_and_dashboard(client):
    alice = make_user()
    tenant = make_tenant(alice, "Firma Alice")
    sign_in(client, alice)
    response = client.get(reverse("tenant:dashboard", args=[tenant.pk]))
    assert response.status_code == 200
    assert "Firma Alice" in response.content.decode()


def test_wrong_password_is_refused(client):
    alice = make_user()
    response = client.post(
        reverse("public:login"), {"identifier": alice.email, "password": "gresit"}
    )
    assert response.status_code == 200
    assert "_auth_user_id" not in client.session


def test_non_member_and_nonexistent_tenant_answer_identically(client):
    alice, bob = make_user(), make_user()
    make_tenant(alice)
    tenant_b = make_tenant(bob)
    sign_in(client, alice)
    foreign = client.get(reverse("tenant:dashboard", args=[tenant_b.pk]))
    missing = client.get(reverse("tenant:dashboard", args=[uuid.uuid4()]))
    assert foreign.status_code == missing.status_code == 404
    assert foreign.content == missing.content


def test_post_into_a_foreign_tenant_changes_nothing(client):
    alice, bob = make_user(), make_user()
    make_tenant(alice)
    tenant_b = create_tenant(bob, name="B", idempotency_key=uuid.uuid4())
    sign_in(client, alice)
    response = client.post(
        reverse("tenant:fiscal-profile", args=[tenant_b.pk]), {"company_name": "Plantat"}
    )
    assert response.status_code == 404
    with db_scope(tenant_id=tenant_b.pk, user_id=bob.pk):
        assert CompanyFiscalProfile.objects.get().company_name == ""


def test_read_only_role_cannot_reach_members_page(client):
    alice, carol = make_user(), make_user()
    tenant = make_tenant(alice)
    with db_scope(tenant_id=tenant.pk, user_id=alice.pk):
        TenantMembership.objects.create(tenant=tenant, user=carol, role=Role.READ_ONLY)
    sign_in(client, carol)
    assert client.get(reverse("tenant:members", args=[tenant.pk])).status_code == 403
    assert client.get(reverse("tenant:dashboard", args=[tenant.pk])).status_code == 200


def test_registration_does_not_reveal_existing_accounts(client):
    alice = make_user()
    data = {"full_name": "X", "password": "o-parola-destul-de-lunga"}
    existing = client.post(reverse("public:register"), {**data, "email": alice.email})
    fresh = client.post(reverse("public:register"), {**data, "email": "nou@example.test"})
    assert existing.status_code == fresh.status_code == 200
    assert existing.content == fresh.content
    assert len(mail.outbox) == 2


def test_registration_verification_tenant_flow(client):
    response = client.post(
        reverse("public:register"),
        {"full_name": "Nou", "email": "nou@example.test", "password": "o-parola-destul-de-lunga"},
    )
    assert response.status_code == 200
    with db_scope(lookup_email="nou@example.test"):
        user = User.objects.get(email="nou@example.test")
    assert user.email_verified_at is None

    client.post(
        reverse("public:login"),
        {"identifier": "nou@example.test", "password": "o-parola-destul-de-lunga"},
    )
    key = uuid.uuid4()
    refused = client.post(reverse("account:tenant-new"), {"name": "F", "idempotency_key": key})
    assert refused.status_code == 200
    assert "Confirmă" in refused.content.decode()

    link = next(line for line in mail.outbox[0].body.splitlines() if "/verificare-email/" in line)
    assert client.get(link).status_code == 200

    # The stored session user was loaded before verification; a new request reloads it.
    created = client.post(reverse("account:tenant-new"), {"name": "F", "idempotency_key": key})
    assert created.status_code == 302
    again = client.post(reverse("account:tenant-new"), {"name": "F", "idempotency_key": key})
    assert again["Location"] == created["Location"]
    with db_scope(user_id=user.pk):
        assert Tenant.objects.filter(created_by=user).count() == 1


def test_invitation_flow_and_single_use(client):
    alice, bob = make_user(), make_user()
    tenant = make_tenant(alice)
    with db_scope(tenant_id=tenant.pk, user_id=alice.pk):
        membership = TenantMembership.objects.get(user=alice)
        token = invite_member(
            tenant_id=tenant.pk,
            invited_by_membership_id=membership.pk,
            email=bob.email,
            role=Role.ACCOUNTANT,
        )
    sign_in(client, bob)
    url = reverse("account:invitation-accept", args=[token])
    assert client.post(url).status_code == 302
    assert client.get(reverse("tenant:dashboard", args=[tenant.pk])).status_code == 200
    second = client.post(url)
    assert second.status_code == 200
    assert "nu este validă" in second.content.decode()


def test_invitation_for_someone_else_is_refused(client):
    alice, bob, eve = make_user(), make_user(), make_user()
    tenant = make_tenant(alice)
    with db_scope(tenant_id=tenant.pk, user_id=alice.pk):
        membership = TenantMembership.objects.get(user=alice)
        token = invite_member(
            tenant_id=tenant.pk,
            invited_by_membership_id=membership.pk,
            email=bob.email,
            role=Role.MEMBER,
        )
    sign_in(client, eve)
    client.post(reverse("account:invitation-accept", args=[token]))
    assert client.get(reverse("tenant:dashboard", args=[tenant.pk])).status_code == 404


def test_login_is_throttled(client):
    alice = make_user()
    for _ in range(10):
        client.post(reverse("public:login"), {"identifier": alice.email, "password": "gresit"})
    response = client.post(
        reverse("public:login"), {"identifier": alice.email, "password": PASSWORD}
    )
    assert response.status_code == 429


def test_seed_is_refused_outside_development(settings):
    settings.DEBUG = True
    settings.AAI_ALLOW_DEV_SEED = False
    with pytest.raises(CommandError):
        call_command("seed_dev")
    settings.DEBUG = False
    settings.AAI_ALLOW_DEV_SEED = True
    with pytest.raises(CommandError):
        call_command("seed_dev")


def test_seed_creates_admin_who_can_log_in_and_is_idempotent(client, settings):
    settings.DEBUG = True
    settings.AAI_ALLOW_DEV_SEED = True
    call_command("seed_dev")
    call_command("seed_dev")
    response = client.post(
        reverse("public:login"), {"identifier": "admin", "password": "1234"}
    )
    assert response.status_code == 302
    follow = client.get(reverse("account:tenant-list"), follow=True)
    assert follow.status_code == 200
    assert "Firmă Demo SRL" in follow.content.decode()
    assert len(follow.redirect_chain) == 1


def test_password_reset_flow(client):
    alice = make_user()
    mail.outbox.clear()
    client.post(reverse("public:password-reset"), {"email": alice.email})
    link = next(line for line in mail.outbox[0].body.splitlines() if "/resetare-parola/" in line)
    new_password = "o-parola-noua-si-lunga"
    response = client.post(
        link, {"password": new_password, "password_again": new_password}
    )
    assert response.status_code == 302
    other = "alta-parola-lunga-aici"
    assert client.post(link, {"password": other, "password_again": other}).status_code == 400
    assert client.post(
        reverse("public:login"), {"identifier": alice.email, "password": new_password}
    ).status_code == 302


def test_password_reset_does_not_reveal_accounts(client):
    alice = make_user()
    mail.outbox.clear()
    known = client.post(reverse("public:password-reset"), {"email": alice.email})
    unknown = client.post(reverse("public:password-reset"), {"email": "nimeni@example.test"})
    assert known.content == unknown.content
    assert len(mail.outbox) == 1


def test_open_redirect_is_refused_at_login(client):
    alice = make_user()
    response = client.post(
        reverse("public:login"),
        {"identifier": alice.email, "password": PASSWORD, "next": "https://rau.example/"},
    )
    assert response["Location"] == reverse("account:tenant-list")
