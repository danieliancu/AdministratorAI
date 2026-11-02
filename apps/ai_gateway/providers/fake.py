import hashlib
import math
import re

from django.conf import settings

from .base import (
    EmbedResult,
    ProviderAdapter,
    ProviderNotConfigured,
    ProviderRequest,
    ProviderResult,
)

SYNTHETIC_TEXT = "[RĂSPUNS SINTETIC: provider de test, nu este un rezultat AI real.]"
EMBEDDING_DIMENSIONS = 1536


def _hashed_vector(text):
    """Word and letter hashes: stable and able to find shared words, but not meaning.

    Good enough to exercise the pipeline. It says nothing about semantic search quality.
    """
    vector = [0.0] * EMBEDDING_DIMENSIONS
    for word in re.findall(r"\w+", text.lower()):
        pieces = [word] + [word[i : i + 3] for i in range(max(len(word) - 2, 0))]
        for piece in pieces:
            digest = hashlib.sha256(piece.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % EMBEDDING_DIMENSIONS
            vector[index] += 1.0 if digest[4] % 2 else -1.0
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class FakeAdapter(ProviderAdapter):
    """For development and tests. Refuses to run unless explicitly allowed, and labels its text."""

    def complete(self, request: ProviderRequest) -> ProviderResult:
        if not settings.AAI_ALLOW_FAKE_AI:
            raise ProviderNotConfigured("The fake provider is not allowed here")
        input_tokens = (len(request.system_prompt) + len(request.user_prompt)) // 4 + 1
        output_tokens = min(request.max_output_tokens, 20)
        return ProviderResult(
            output_text=SYNTHETIC_TEXT,
            status="completed",
            usage_known=True,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            raw_usage={"input_tokens": input_tokens, "output_tokens": output_tokens},
            request_id="fake",
            is_synthetic=True,
        )

    def embed(self, model_name, texts):
        if not settings.AAI_ALLOW_FAKE_AI:
            raise ProviderNotConfigured("The fake provider is not allowed here")
        return EmbedResult(
            vectors=[_hashed_vector(text) for text in texts],
            usage_known=True,
            input_tokens=sum(len(text) // 4 + 1 for text in texts),
            is_synthetic=True,
        )
