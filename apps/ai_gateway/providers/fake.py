from django.conf import settings

from .base import ProviderAdapter, ProviderNotConfigured, ProviderRequest, ProviderResult

SYNTHETIC_TEXT = "[RĂSPUNS SINTETIC: provider de test, nu este un rezultat AI real.]"


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
