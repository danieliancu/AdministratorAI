import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.accounts.models import User
from apps.core.db.scope import db_scope
from apps.tenants.models import Tenant
from apps.tenants.services import create_tenant

LOGIN = "admin"
PASSWORD = "1234"  # noqa: S105 - requested development credential, refused outside dev
TENANT_NAME = "Firmă Demo SRL (fictivă)"
TENANT_KEY = uuid.UUID("00000000-0000-4000-8000-00000000d3a0")


class Command(BaseCommand):
    help = "Create the fictional development tenant and its admin account. Development only."

    def handle(self, *args, **options):
        if not (settings.DEBUG and settings.AAI_ALLOW_DEV_SEED):
            raise CommandError("seed_dev is refused outside the development settings.")

        with db_scope(lookup_email=LOGIN):
            user = User.objects.filter(email=LOGIN).first()
        if user is None:
            user_id = uuid.uuid4()
            with db_scope(user_id=user_id):
                user = User.objects.create_user(
                    id=user_id,
                    email=LOGIN,
                    password=PASSWORD,
                    full_name="Administrator Demo",
                    email_verified_at=timezone.now(),
                )
        else:
            # Set directly: the password policy applies to real accounts, not to this seed.
            user.set_password(PASSWORD)
            with db_scope(user_id=user.pk):
                user.save(update_fields=["password"])

        tenant = create_tenant(user, name=TENANT_NAME, idempotency_key=TENANT_KEY)
        with db_scope(user_id=user.pk):
            assert Tenant.objects.filter(pk=tenant.pk).exists()  # noqa: S101
        self.stdout.write(f"Ready: login={LOGIN} tenant={tenant.pk}")
