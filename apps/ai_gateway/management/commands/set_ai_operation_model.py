from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.ai_gateway.models import AIModel, AIModelPricing, AIOperation


class Command(BaseCommand):
    help = (
        "Choose the model an operation uses. The model must have a price in force, so no "
        "request can run uncosted. Needs owner credentials: run it in the migrate service."
    )

    def add_arguments(self, parser):
        parser.add_argument("--operation", required=True)
        parser.add_argument("--model", required=True, help="Model key, such as openai:gpt-6-luna")

    def handle(self, *args, operation, model, **options):
        chosen = AIModel.objects.filter(pk=model, is_active=True).first()
        if chosen is None:
            raise CommandError(f"No active model {model}. Add it with set_ai_model_price.")
        if not AIModelPricing.objects.filter(
            model=chosen, effective_from__lte=timezone.now()
        ).exists():
            raise CommandError(f"Model {model} has no price in force.")
        if not AIOperation.objects.filter(pk=operation).update(default_model=chosen):
            raise CommandError(f"No operation {operation}.")
        self.stdout.write(f"Operation {operation} now uses {model}")
