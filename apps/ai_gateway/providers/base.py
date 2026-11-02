from dataclasses import dataclass, field


class ProviderError(Exception):
    pass


class ProviderNotProcessed(ProviderError):
    """The provider certainly did not charge: the reservation can be released."""


class ProviderNotConfigured(ProviderNotProcessed):
    pass


class ProviderRejected(ProviderNotProcessed):
    pass


class ProviderRetryable(ProviderNotProcessed):
    """Not processed, and worth a bounded retry, such as a rate limit."""


class ProviderOutcomeUnknown(ProviderError):
    """Timeout, dropped connection or server error: we may have been charged."""


@dataclass(frozen=True)
class ProviderRequest:
    provider_model_name: str
    system_prompt: str
    user_prompt: str
    max_output_tokens: int
    output_schema: dict | None = None
    schema_name: str = "result"


@dataclass(frozen=True)
class ProviderResult:
    output_text: str
    status: str  # completed, incomplete or refused
    usage_known: bool
    input_tokens: int = 0
    cached_tokens: int = 0
    cache_write_30m_tokens: int = 0
    cache_write_12h_tokens: int = 0
    output_tokens: int = 0
    raw_usage: dict = field(default_factory=dict)
    request_id: str = ""
    is_synthetic: bool = False


class ProviderAdapter:
    def complete(self, request: ProviderRequest) -> ProviderResult:
        raise NotImplementedError
