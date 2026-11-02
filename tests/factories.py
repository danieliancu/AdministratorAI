import uuid

from django.utils import timezone

from apps.accounts.models import User
from apps.core.db.scope import db_scope
from apps.tenants.models import Tenant, TenantMembership
from apps.tenants.roles import Role


def make_user(email=None, password="correct-horse-battery"):
    user_id = uuid.uuid4()
    email = email or f"{user_id.hex}@example.test"
    with db_scope(user_id=user_id):
        return User.objects.create_user(
            id=user_id, email=email, password=password, email_verified_at=timezone.now()
        )


def make_tenant(owner, name="Firma"):
    tenant_id = uuid.uuid4()
    with db_scope(tenant_id=tenant_id, user_id=owner.pk):
        tenant = Tenant.objects.create(id=tenant_id, name=name, created_by=owner)
        TenantMembership.objects.create(tenant=tenant, user=owner, role=Role.OWNER)
    return tenant
