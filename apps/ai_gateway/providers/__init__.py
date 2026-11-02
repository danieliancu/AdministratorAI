from .base import ProviderNotConfigured
from .fake import FakeAdapter


def get_adapter(provider_key):
    if provider_key == "fake":
        return FakeAdapter()
    if provider_key == "openai":
        # Imported here so only this path loads the SDK.
        from .openai_adapter import OpenAIAdapter

        return OpenAIAdapter()
    raise ProviderNotConfigured(f"No adapter for provider {provider_key}")
