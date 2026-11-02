from dataclasses import dataclass

VIEW = "view"
MANAGE = "manage"

CAPABILITIES = {
    "superadmin": {VIEW, MANAGE},
    "support": {VIEW},
}


@dataclass(frozen=True)
class PlatformAccess:
    role: str

    def can(self, capability):
        return capability in CAPABILITIES[self.role]


def requires_platform(capability):
    """Declare what a platform view needs. DbScopeMiddleware refuses views without it."""

    def decorator(view):
        view.required_platform_capability = capability
        return view

    return decorator


def load_platform_access(user_id):
    """Runs in the user's own scope: the runtime role can read only its own grant."""
    from apps.accounts.models import PlatformGrant

    grant = PlatformGrant.objects.filter(user_id=user_id).first()
    return PlatformAccess(role=grant.role) if grant else None
