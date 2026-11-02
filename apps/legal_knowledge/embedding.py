"""Embeds legal text once per distinct text and model. All provider calls use the gateway."""

from django.conf import settings

from apps.ai_gateway.embeddings import EmbeddingUnavailable, embed_texts

from .ingestion import LEGAL
from .models import EMBEDDING_DIMENSIONS, LegalChunk, LegalEmbedding

BATCH_SIZE = 64


def pending_texts(model_key, limit):
    done = LegalEmbedding.objects.using(LEGAL).filter(model_key=model_key).values("checksum")
    rows = (
        LegalChunk.objects.using(LEGAL)
        .exclude(checksum__in=done)
        .values_list("checksum", "normalized_text")
        .distinct("checksum")
        .order_by("checksum")[:limit]
    )
    return list(rows)


def embed_pending(*, model_key=None, limit=500, adapter=None):
    """Returns how many texts were embedded. Without budget or a key, the rest stay pending."""
    model_key = model_key or settings.AAI_LEGAL_EMBEDDING_MODEL
    total = 0
    pending = pending_texts(model_key, limit)
    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start : start + BATCH_SIZE]
        try:
            result = embed_texts(
                [text for _, text in batch],
                model_key=model_key,
                using=LEGAL,
                purpose="legal_corpus",
                adapter=adapter,
            )
        except EmbeddingUnavailable:
            break
        if any(len(vector) != EMBEDDING_DIMENSIONS for vector in result.vectors):
            raise ValueError("Unexpected embedding size")
        LegalEmbedding.objects.using(LEGAL).bulk_create(
            [
                LegalEmbedding(
                    checksum=checksum,
                    model_key=model_key,
                    embedding=vector,
                    is_synthetic=result.is_synthetic,
                )
                for (checksum, _), vector in zip(batch, result.vectors, strict=True)
            ],
            ignore_conflicts=True,
        )
        total += len(batch)
    return total
