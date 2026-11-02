from django.core.management.base import BaseCommand

from apps.legal_knowledge.embedding import embed_pending


class Command(BaseCommand):
    help = "Embed legal text without an embedding yet. Run it in the worker service."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=500)

    def handle(self, *args, limit, **options):
        self.stdout.write(f"Embedded {embed_pending(limit=limit)}")
