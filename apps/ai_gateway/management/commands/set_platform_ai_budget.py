import json
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import connection
from django.utils import timezone

from apps.ai_gateway.gateway import billing_period
from apps.ai_gateway.models import AIPlatformBudget


class Command(BaseCommand):
    help = "Set this month's platform AI budget, used for indexing. Needs owner credentials."

    def add_arguments(self, parser):
        parser.add_argument("--limit", required=True, type=Decimal)
        parser.add_argument("--currency", default="USD")
        parser.add_argument("--reason", required=True)

    def handle(self, *args, limit, currency, reason, **options):
        start, end = billing_period(timezone.now(), 1)
        AIPlatformBudget.objects.update_or_create(
            period_start=start,
            defaults={"period_end": end, "currency": currency, "limit_amount": limit},
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT platform.record_event("
                "NULL, 'ai.platform_budget.set', NULL, %s, %s::jsonb)",
                [reason, json.dumps({"limit": str(limit), "currency": currency})],
            )
        self.stdout.write(f"Platform budget {limit} {currency} for {start:%Y-%m}")
