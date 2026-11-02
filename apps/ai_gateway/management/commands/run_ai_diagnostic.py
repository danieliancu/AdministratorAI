import uuid

from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User, normalize_login
from apps.ai_gateway.tasks import run_diagnostic
from apps.core.db.scope import db_scope
from apps.core.tasks import enqueue
from apps.tenants.models import TenantMembership


class Command(BaseCommand):
    help = (
        "Queue one diagnostic request through the gateway, for a member of a firm. "
        "It is charged to that firm's AI budget, and a real provider will bill for it."
    )

    def add_arguments(self, parser):
        parser.add_argument("login")

    def handle(self, *args, login, **options):
        login = normalize_login(login)
        with db_scope(lookup_email=login):
            user = User.objects.filter(email=login).first()
        if user is None:
            raise CommandError(f"No account with login {login}")
        with db_scope(user_id=user.pk):
            tenant_id = (
                TenantMembership.objects.filter(user=user)
                .values_list("tenant_id", flat=True)
                .first()
            )
        if tenant_id is None:
            raise CommandError(f"{login} is not a member of any firm")
        with db_scope(tenant_id=tenant_id, user_id=user.pk):
            enqueue(
                run_diagnostic,
                idempotency_key=str(uuid.uuid4()),
                note="Test de diagnostic pornit de operator.",
            )
        self.stdout.write(f"Queued for tenant {tenant_id}")
