"""The only module allowed to import the OpenAI SDK. A test enforces this.

Tested against simulated HTTP responses shaped like the documentation. It has not yet
made a real call, because no API key is configured.
"""

import openai
from django.conf import settings

from .base import (
    ProviderAdapter,
    ProviderNotConfigured,
    ProviderOutcomeUnknown,
    ProviderRejected,
    ProviderRequest,
    ProviderResult,
    ProviderRetryable,
)


def _as_dict(value):
    return value.model_dump() if hasattr(value, "model_dump") else (value or {})


def parse_usage(usage):
    """Returns the token counts, or None when the provider did not report them."""
    usage = _as_dict(usage)
    if not usage or usage.get("input_tokens") is None or usage.get("output_tokens") is None:
        return None
    details = usage.get("input_tokens_details") or {}
    cached = details.get("cached_tokens") or 0
    writes = details.get("cache_write_tokens") or 0
    split = details.get("cache_write_tokens_details") or {}
    write_30m = split.get("ttl_30m_tokens") or 0
    write_12h = split.get("ttl_12h_tokens") or 0
    # Writes without a lifetime split are priced at the dearer rate: over, never under.
    write_12h += max(writes - write_30m - write_12h, 0)
    return {
        "input_tokens": usage["input_tokens"],
        "cached_tokens": cached,
        "cache_write_30m_tokens": write_30m,
        "cache_write_12h_tokens": write_12h,
        "output_tokens": usage["output_tokens"],
        "raw_usage": usage,
    }


def _collect_output(response):
    texts, refused = [], False
    for item in response.get("output") or []:
        for part in item.get("content") or []:
            if part.get("type") == "output_text":
                texts.append(part.get("text") or "")
            elif part.get("type") == "refusal":
                refused = True
    return "".join(texts), refused


def parse_response(response):
    response = _as_dict(response)
    text, refused = _collect_output(response)
    if refused:
        status = "refused"
    elif response.get("status") == "completed":
        status = "completed"
    else:
        status = "incomplete"
    usage = parse_usage(response.get("usage"))
    return ProviderResult(
        output_text=text,
        status=status,
        usage_known=usage is not None,
        request_id=response.get("id") or "",
        **(usage or {}),
    )


class OpenAIAdapter(ProviderAdapter):
    def __init__(self, http_client=None):
        self._http_client = http_client

    def _client(self):
        if not settings.OPENAI_API_KEY:
            raise ProviderNotConfigured("OPENAI_API_KEY is not set")
        # max_retries=0: the gateway owns retries, because each one can cost money.
        options = {"http_client": self._http_client} if self._http_client else {}
        return openai.OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.AAI_AI_TIMEOUT_SECONDS,
            max_retries=0,
            **options,
        )

    def complete(self, request: ProviderRequest) -> ProviderResult:
        arguments = {
            "model": request.provider_model_name,
            "instructions": request.system_prompt,
            "input": request.user_prompt,
            "max_output_tokens": request.max_output_tokens,
            # Do not keep confidential company data with the provider longer than needed.
            "store": False,
        }
        if request.output_schema:
            arguments["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": request.schema_name,
                    "strict": True,
                    "schema": request.output_schema,
                }
            }
        try:
            response = self._client().responses.create(**arguments)
        except openai.RateLimitError as exc:
            raise ProviderRetryable(str(exc.status_code)) from exc
        except openai.InternalServerError as exc:
            raise ProviderOutcomeUnknown(str(exc.status_code)) from exc
        except openai.APIStatusError as exc:
            raise ProviderRejected(str(exc.status_code)) from exc
        except openai.APIError as exc:
            # Includes timeouts and dropped connections: the request may have been processed.
            raise ProviderOutcomeUnknown(type(exc).__name__) from exc
        return parse_response(response)
