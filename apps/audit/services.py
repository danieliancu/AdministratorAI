import hashlib

from apps.accounts.models import normalize_login
from apps.core.db.scope import current_scope

from .models import SecurityEvent, TenantEvent


def record_tenant_event(action, *, actor_user_id=None, metadata=None):
    """Runs inside the tenant scope, so the event commits or rolls back with the change."""
    TenantEvent.objects.create(
        tenant_id=current_scope().tenant_id,
        actor_user_id=actor_user_id,
        action=action,
        metadata=metadata or {},
    )


def record_security_event(action, *, request=None, actor_user_id=None, identifier=""):
    # The identifier is hashed: failed logins often hold a mistyped password or someone's email.
    digest = hashlib.sha256(normalize_login(identifier).encode()).hexdigest() if identifier else ""
    SecurityEvent.objects.create(
        action=action,
        actor_user_id=actor_user_id,
        identifier_hash=digest,
        ip_address=request.META.get("REMOTE_ADDR", "") if request else "",
    )
