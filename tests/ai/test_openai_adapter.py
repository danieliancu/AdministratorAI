"""Simulated HTTP, shaped like the documentation. This does not prove the real API behaves so."""

import ast
import json
from pathlib import Path

import httpx2
import pytest
from django.conf import settings as django_settings

from apps.ai_gateway.providers.base import (
    ProviderNotConfigured,
    ProviderOutcomeUnknown,
    ProviderRejected,
    ProviderRequest,
    ProviderRetryable,
)
from apps.ai_gateway.providers.openai_adapter import OpenAIAdapter, parse_usage

REQUEST = ProviderRequest(
    provider_model_name="some-model",
    system_prompt="SYSTEM",
    user_prompt="USER",
    max_output_tokens=50,
)


def success_body(**overrides):
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 0,
        "model": "some-model",
        "parallel_tool_calls": False,
        "tool_choice": "auto",
        "tools": [],
        "status": "completed",
        "output": [
            {
                "type": "message",
                "id": "msg_1",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "Salut", "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 40},
            "output_tokens": 10,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 110,
        },
        **overrides,
    }


def adapter_with(handler):
    return OpenAIAdapter(http_client=httpx2.Client(transport=httpx2.MockTransport(handler)))


@pytest.fixture(autouse=True)
def api_key(settings):
    settings.OPENAI_API_KEY = "sk-test-not-real"


def test_success_is_parsed_and_the_request_is_minimal():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=success_body())

    result = adapter_with(handler).complete(REQUEST)
    assert result.output_text == "Salut"
    assert result.status == "completed"
    assert result.usage_known
    assert (result.input_tokens, result.cached_tokens, result.output_tokens) == (100, 40, 10)
    assert result.request_id == "resp_1"
    assert not result.is_synthetic
    assert seen[0]["store"] is False
    assert seen[0]["max_output_tokens"] == 50
    assert seen[0]["instructions"] == "SYSTEM"
    assert seen[0]["input"] == "USER"


def test_structured_output_is_requested_strictly():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(200, json=success_body())

    schema = {"type": "object"}
    adapter_with(handler).complete(
        ProviderRequest(
            provider_model_name="m",
            system_prompt="S",
            user_prompt="U",
            max_output_tokens=5,
            output_schema=schema,
        )
    )
    text_format = seen[0]["text"]["format"]
    assert text_format["type"] == "json_schema"
    assert text_format["strict"] is True
    assert text_format["schema"] == schema


@pytest.mark.parametrize(
    "status,expected",
    [
        (429, ProviderRetryable),
        (400, ProviderRejected),
        (401, ProviderRejected),
        (500, ProviderOutcomeUnknown),
        (503, ProviderOutcomeUnknown),
    ],
)
def test_status_codes(status, expected):
    calls = []

    def handler(request):
        calls.append(1)
        return httpx2.Response(status, json={"error": {"message": "x"}})

    with pytest.raises(expected):
        adapter_with(handler).complete(REQUEST)
    # The SDK must not retry on its own: every retry could cost money unaccounted for.
    assert len(calls) == 1


@pytest.mark.parametrize(
    "error",
    [httpx2.ReadTimeout("slow"), httpx2.ConnectError("gone"), httpx2.RemoteProtocolError("x")],
)
def test_network_failures_are_treated_as_possibly_charged(error):
    def handler(request):
        raise error

    with pytest.raises(ProviderOutcomeUnknown):
        adapter_with(handler).complete(REQUEST)


def test_refusal_and_incomplete_are_not_presented_as_answers():
    refused = success_body(
        output=[
            {
                "type": "message",
                "id": "m",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "refusal", "refusal": "Nu pot."}],
            }
        ]
    )
    result = adapter_with(lambda r: httpx2.Response(200, json=refused)).complete(REQUEST)
    assert result.status == "refused"

    cut = success_body(status="incomplete", incomplete_details={"reason": "max_output_tokens"})
    result = adapter_with(lambda r: httpx2.Response(200, json=cut)).complete(REQUEST)
    assert result.status == "incomplete"


def test_missing_usage_is_reported_as_unknown():
    body = success_body(usage=None)
    result = adapter_with(lambda r: httpx2.Response(200, json=body)).complete(REQUEST)
    assert not result.usage_known


def test_embeddings_are_parsed_in_order_and_not_retried():
    calls = []

    def handler(request):
        calls.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "object": "list",
                "model": "m",
                "data": [
                    {"object": "embedding", "index": 1, "embedding": [0.2]},
                    {"object": "embedding", "index": 0, "embedding": [0.1]},
                ],
                "usage": {"prompt_tokens": 9, "total_tokens": 9},
            },
        )

    result = adapter_with(handler).embed("m", ["a", "b"])
    assert result.vectors == [[0.1], [0.2]]
    assert result.input_tokens == 9
    assert result.usage_known
    assert not result.is_synthetic
    assert len(calls) == 1


def test_no_key_means_not_configured(settings):
    settings.OPENAI_API_KEY = ""
    with pytest.raises(ProviderNotConfigured):
        OpenAIAdapter().complete(REQUEST)


def test_parse_usage_with_cache_writes_split_by_lifetime():
    parsed = parse_usage(
        {
            "input_tokens": 12000,
            "output_tokens": 0,
            "input_tokens_details": {
                "cached_tokens": 4000,
                "cache_write_tokens": 7000,
                "cache_write_tokens_details": {"ttl_30m_tokens": 3000, "ttl_12h_tokens": 4000},
            },
        }
    )
    assert parsed["cache_write_30m_tokens"] == 3000
    assert parsed["cache_write_12h_tokens"] == 4000
    assert parsed["cached_tokens"] == 4000


def test_parse_usage_prices_unsplit_writes_at_the_dearer_rate():
    parsed = parse_usage(
        {
            "input_tokens": 100,
            "output_tokens": 0,
            "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 60},
        }
    )
    assert parsed["cache_write_12h_tokens"] == 60
    assert parsed["cache_write_30m_tokens"] == 0


def test_only_the_adapter_imports_a_provider_sdk():
    """No module may reach a provider except through the gateway."""
    root = Path(django_settings.BASE_DIR)
    allowed = root / "apps/ai_gateway/providers/openai_adapter.py"
    offenders = []
    for folder in ("apps", "config", "templates"):
        for path in (root / folder).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module or ""]
                if any(n.split(".")[0] in ("openai", "anthropic") for n in names):
                    if path != allowed:
                        offenders.append(str(path))
    assert offenders == []


def test_the_api_key_never_reaches_templates_or_static_files():
    root = Path(django_settings.BASE_DIR)
    for folder in ("templates", "static/css"):
        for path in (root / folder).rglob("*"):
            if path.is_file():
                assert "OPENAI_API_KEY" not in path.read_text(encoding="utf-8"), path
