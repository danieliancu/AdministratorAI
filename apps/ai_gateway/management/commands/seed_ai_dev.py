from datetime import UTC, datetime
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import User
from apps.ai_gateway.models import AIBudgetPolicy, AIModel, AIModelPricing, AIOperation, AIProvider
from apps.core.db.scope import db_scope
from apps.tenants.models import TenantMembership

MODEL_KEY = "fake:fake-small"
OPERATION = "diagnostic.echo"


class Command(BaseCommand):
    help = (
        "Install the fake AI provider with made-up prices and enable it for the demo firm. "
        "Development only. Needs owner credentials: run it in the migrate service."
    )

    def handle(self, *args, **options):
        if not settings.AAI_ALLOW_FAKE_AI:
            raise CommandError("seed_ai_dev is refused where the fake provider is not allowed.")

        provider, _ = AIProvider.objects.get_or_create(
            key="fake", defaults={"name": "Provider de test (sintetic)"}
        )
        model, _ = AIModel.objects.get_or_create(
            key=MODEL_KEY, defaults={"provider": provider, "provider_model_name": "fake-small"}
        )
        AIModelPricing.objects.get_or_create(
            model=model,
            effective_from=datetime(2026, 1, 1, tzinfo=UTC),
            defaults={
                "currency": "USD",
                "input_per_mtok": Decimal("1"),
                "cached_read_per_mtok": Decimal("0.1"),
                "cache_write_30m_per_mtok": Decimal("1.25"),
                "cache_write_12h_per_mtok": Decimal("2.5"),
                "output_per_mtok": Decimal("4"),
                "source_url": "development-only: invented prices, not from any provider",
            },
        )
        AIOperation.objects.filter(pk=OPERATION).update(default_model=model)

        with db_scope(lookup_email="admin"):
            admin = User.objects.filter(email="admin").first()
        if admin is None:
            raise CommandError("Run seed_dev first.")
        with db_scope(user_id=admin.pk):
            tenant_id = (
                TenantMembership.objects.filter(user=admin)
                .values_list("tenant_id", flat=True)
                .first()
            )
        with db_scope(tenant_id=tenant_id):
            AIBudgetPolicy.objects.update_or_create(
                tenant_id=tenant_id,
                defaults={
                    "monthly_limit": Decimal("0.01"),
                    "max_cost_per_request": Decimal("0.005"),
                    "max_output_tokens": 200,
                    "allowed_models": [MODEL_KEY],
                    "allowed_operations": [OPERATION],
                },
            )
        self.stdout.write(f"Fake AI enabled for tenant {tenant_id}")
