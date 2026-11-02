from django.core.management.base import BaseCommand, CommandError

from apps.ai_gateway.exchange import BNR_URL, RateUnavailable, parse_bnr
from apps.ai_gateway.models import AIExchangeRate
from apps.legal_knowledge.connectors.http import SourceError, fetch


class Command(BaseCommand):
    help = (
        "Store today's official USD to RON rate from the National Bank of Romania. "
        "Needs owner credentials: run it in the migrate service."
    )

    def handle(self, *args, **options):
        try:
            content, _content_type = fetch(BNR_URL)
            day, rate = parse_bnr(content, "USD")
        except (SourceError, RateUnavailable) as exc:
            raise CommandError(f"No rate stored: {exc}") from exc
        _row, created = AIExchangeRate.objects.get_or_create(
            base_currency="USD",
            quote_currency="RON",
            effective_date=day,
            defaults={"rate": rate, "source_url": BNR_URL},
        )
        state = "stored" if created else "already stored"
        self.stdout.write(f"1 USD = {rate} RON on {day}: {state}")
