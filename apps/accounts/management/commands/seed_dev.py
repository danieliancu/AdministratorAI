import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.core.db.scope import db_scope
from apps.tenants.services import create_tenant

ADMIN_LOGIN = "admin"
SUPERADMIN_LOGIN = "superadmin"
PASSWORD = "1234"  # noqa: S105 - requested development credential, refused outside dev
TENANT_NAME = "Firmă Demo SRL (fictivă)"
TENANT_KEY = uuid.UUID("00000000-0000-4000-8000-00000000d3a0")


def _ensure_user(login, full_name):
    with db_scope(lookup_email=login):
        user = User.objects.filter(email=login).first()
    if user is None:
        user_id = uuid.uuid4()
        with db_scope(user_id=user_id):
            return User.objects.create_user(
                id=user_id,
                email=login,
                password=PASSWORD,
                full_name=full_name,
                email_verified_at=timezone.now(),
            )
    # Set directly: the password policy applies to real accounts, not to this seed.
    user.set_password(PASSWORD)
    with db_scope(user_id=user.pk):
        user.save(update_fields=["password"])
    return user


class Command(BaseCommand):
    help = "Create the fictional development tenant and its accounts. Development only."

    def handle(self, *args, **options):
        if not (settings.DEBUG and settings.AAI_ALLOW_DEV_SEED):
            raise CommandError("seed_dev is refused outside the development settings.")

        admin = _ensure_user(ADMIN_LOGIN, "Administrator Demo")
        tenant = create_tenant(admin, name=TENANT_NAME, idempotency_key=TENANT_KEY)
        _ensure_user(SUPERADMIN_LOGIN, "Superadmin Demo")
        self.stdout.write(f"Ready: {ADMIN_LOGIN} tenant={tenant.pk}; {SUPERADMIN_LOGIN} account")
        self.stdout.write(
            "Platform access needs owner credentials: docker compose run --rm migrate python "
            f'manage.py grant_platform_role {SUPERADMIN_LOGIN} superadmin --reason "dev seed"'
        )
