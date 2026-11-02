from dataclasses import dataclass


@dataclass(frozen=True)
class TenantAccess:
    """Plain snapshot, so error pages rendered after the scope never touch the database."""

    tenant_id: object
    tenant_name: str
    tenant_status: str
    membership_id: object
    role: str

    @property
    def is_active(self):
        return self.tenant_status == "active"

    @property
    def role_label(self):
        from .roles import Role

        return Role(self.role).label

    def can(self, capability):
        from .roles import CAPABILITIES

        return capability in CAPABILITIES[self.role]


def load_tenant_access(user_id):
    from .models import TenantMembership

    membership = (
        TenantMembership.objects.select_related("tenant")
        .filter(user_id=user_id, is_active=True)
        .first()
    )
    if membership is None:
        return None
    return TenantAccess(
        tenant_id=membership.tenant_id,
        tenant_name=membership.tenant.name,
        tenant_status=membership.tenant.status,
        membership_id=membership.pk,
        role=membership.role,
    )
