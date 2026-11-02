from decimal import Decimal

from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from apps.ai_gateway.models import AIModel, AIModelPricing, AIProvider


class Command(BaseCommand):
    help = (
        "Add a model price per million tokens, from the provider's official price list. "
        "Prices are never edited: a new price is a new row. Needs owner credentials."
    )

    def add_arguments(self, parser):
        parser.add_argument("--provider", required=True)
        parser.add_argument("--model", required=True, help="The name the provider uses")
        for rate in ("input", "cached-read", "cache-write-30m", "cache-write-12h", "output"):
            parser.add_argument(f"--{rate}", required=True, type=Decimal)
        parser.add_argument("--currency", required=True)
        parser.add_argument("--effective-from", required=True, type=parse_datetime)
        parser.add_argument("--source-url", required=True)

    def handle(self, *args, **options):
        provider, _ = AIProvider.objects.get_or_create(
            key=options["provider"], defaults={"name": options["provider"]}
        )
        key = f"{provider.key}:{options['model']}"
        model, _ = AIModel.objects.get_or_create(
            key=key, defaults={"provider": provider, "provider_model_name": options["model"]}
        )
        AIModelPricing.objects.create(
            model=model,
            effective_from=options["effective_from"],
            currency=options["currency"],
            input_per_mtok=options["input"],
            cached_read_per_mtok=options["cached_read"],
            cache_write_30m_per_mtok=options["cache_write_30m"],
            cache_write_12h_per_mtok=options["cache_write_12h"],
            output_per_mtok=options["output"],
            source_url=options["source_url"],
        )
        self.stdout.write(f"Price added for {key}")
