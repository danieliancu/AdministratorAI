from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime

from apps.ai_gateway.embeddings import EmbeddingUnavailable, embed_texts
from apps.legal_knowledge.ingestion import LEGAL
from apps.legal_knowledge.parsing import fold_for_search
from apps.legal_knowledge.retrieval import retrieve


class Command(BaseCommand):
    help = "Search the corpus as of a date, to inspect retrieval. Run it in the worker service."

    def add_arguments(self, parser):
        parser.add_argument("question")
        parser.add_argument("--date", required=True, type=date.fromisoformat)
        parser.add_argument("--known-at", type=parse_datetime)
        parser.add_argument("--limit", type=int, default=5)

    def handle(self, *args, question, date, known_at, limit, **options):
        model = settings.AAI_LEGAL_EMBEDDING_MODEL
        vector = None
        try:
            vector = embed_texts(
                [fold_for_search(question)], model_key=model, using=LEGAL, purpose="legal_search"
            ).vectors[0]
        except EmbeddingUnavailable as exc:
            self.stdout.write(f"No semantic search: {exc}")
        result = retrieve(
            question,
            on_date=date,
            known_at=known_at,
            limit=limit,
            query_vector=vector,
            embedding_model=model if vector else None,
            using=LEGAL,
        )
        for item in result.evidence:
            self.stdout.write(
                f"{item.score:.4f} {item.citation} {item.article} {item.paragraph} "
                f"[{item.valid_from} – {item.valid_to or '…'}] {item.official_url}"
            )
            self.stdout.write(f"    {item.text[:160]}")
            for warning in item.warnings:
                self.stdout.write(f"    ! {warning}")
        for limitation in result.limitations:
            self.stdout.write(f"LIMITATION: {limitation}")
