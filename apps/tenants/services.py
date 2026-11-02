import hashlib
import secrets
import uuid
from datetime import timedelta

from django.db import IntegrityError, connection
from django.utils import timezone

from apps.accounts.models import normalize_login
from apps.audit.services import record_tenant_event
from apps.core.db.scope import current_scope, db_scope

from .models import (
    CompanyFiscalProfile,
    Tenant,
    TenantInvitation,
    TenantMembership,
    TenantSettings,
)
from .roles import Role

MAX_TENANTS_PER_USER = 10
INVITATION_DAYS = 7


class TenantError(Exception):
    pass


class EmailNotVerified(TenantError):
    pass


class QuotaExceeded(TenantError):
    pass


class InvitationInvalid(TenantError):
    pass


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_tenant(user, *, name, idempotency_key):
    if user.email_verified_at is None:
        raise EmailNotVerified
    with db_scope(user_id=user.pk):
        # Transaction-scoped lock, safe under PgBouncer: concurrent requests from
        # one user queue up here, so they cannot pass the quota check together.
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [str(user.pk)]
            )
        existing = Tenant.objects.filter(
            created_by=user, idempotency_key=idempotency_key
        ).first()
        if existing is not None:
            return existing
        if TenantMembership.objects.count() >= MAX_TENANTS_PER_USER:
            raise QuotaExceeded

        # The context is set before the row exists, so creation needs no privileged path.
        tenant_id = uuid.uuid4()
        with db_scope(tenant_id=tenant_id, user_id=user.pk):
            tenant = Tenant.objects.create(
                id=tenant_id, name=name, created_by=user, idempotency_key=idempotency_key
            )
            TenantMembership.objects.create(tenant=tenant, user=user, role=Role.OWNER)
            TenantSettings.objects.create(tenant=tenant)
            CompanyFiscalProfile.objects.create(tenant=tenant)
            record_tenant_event("tenant.created", actor_user_id=user.pk)
    return tenant


def invite_member(*, tenant_id, invited_by_membership_id, email, role):
    """Runs inside the tenant scope. Returns the token, which is stored only as a hash."""
    token = secrets.token_urlsafe(32)
    TenantInvitation.objects.create(
        tenant_id=tenant_id,
        email=normalize_login(email),
        role=role,
        token_hash=hash_token(token),
        invited_by_id=invited_by_membership_id,
        expires_at=timezone.now() + timedelta(days=INVITATION_DAYS),
    )
    record_tenant_event(
        "member.invited",
        actor_user_id=current_scope().user_id,
        metadata={"role": role},
    )
    return token


def accept_invitation(user, token):
    token_hash = hash_token(token)
    if user.email_verified_at is None:
        raise EmailNotVerified
    with db_scope(user_id=user.pk, invite_token_hash=token_hash):
        invitation = TenantInvitation.objects.filter(token_hash=token_hash).first()
    if invitation is None or invitation.email != user.email:
        raise InvitationInvalid

    with db_scope(tenant_id=invitation.tenant_id, user_id=user.pk):
        accepted = TenantInvitation.objects.filter(
            pk=invitation.pk, accepted_at__isnull=True, expires_at__gt=timezone.now()
        ).update(accepted_at=timezone.now(), accepted_by=user)
        if not accepted:
            raise InvitationInvalid
        try:
            with db_scope(tenant_id=invitation.tenant_id, user_id=user.pk):
                TenantMembership.objects.create(
                    tenant_id=invitation.tenant_id, user=user, role=invitation.role
                )
        except IntegrityError as exc:
            raise InvitationInvalid from exc
        record_tenant_event(
            "member.joined", actor_user_id=user.pk, metadata={"role": invitation.role}
        )
    return invitation.tenant_id
