import asyncio
import importlib
import importlib.util
import json
import traceback
from dataclasses import replace
from typing import Any

import httpx
import pytest

from ai_workshop.labs.rag.deployments.domain import ProviderKind
from ai_workshop.labs.rag.generation.domain import ContextualizationRequest
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    GenerationTermination,
    tracked_generation_call,
)
from tests.unit.labs.rag.generation.test_openai_responses import (
    MODEL_ID,
    generation_request,
    profile,
    structured_text,
)

MODULE = "ai_workshop.labs.rag.generation.anthropic_messages"
SECRET = "synthetic-private-credential"


def native_profile():
    assert "anthropic_messages" in ProviderKind._value2member_map_
    original = profile()
    return replace(
        original,
        deployment=replace(original.deployment, provider=ProviderKind("anthropic_messages")),
        temperature=1.0,
        sampling_mode="provider_default",
    )


def response_payload(**overrides: object) -> dict[str, Any]:
    return {
        "type": "message",
        "role": "assistant",
        "model": MODEL_ID,
        "stop_reason": "end_turn",
        "stop_details": None,
        "stop_sequence": None,
        "content": [{"type": "text", "text": structured_text()}],
        "usage": {
            "input_tokens": 10,
            "output_tokens": 7,
            "cache_creation_input_tokens": 20,
            "cache_read_input_tokens": 30,
        },
        **overrides,
    }


def runtime(handler, *, retries: int = 0, endpoint: str = "https://provider.example.test/v1"):
    assert importlib.util.find_spec(MODULE) is not None, "Native Anthropic adapter is required"
    module = importlib.import_module(MODULE)
    selected = replace(native_profile().deployment, max_retries=retries)
    return module.AnthropicMessagesRuntime._for_test(
        deployment=selected,
        endpoint=endpoint,
        api_key=SECRET,
        transport=httpx.MockTransport(handler),
    )


async def test_native_wire_and_cache_usage_preserve_shared_grounding_contract():
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            json=response_payload(
                content=[
                    {"type": "thinking", "thinking": "private reasoning never stored"},
                    {"type": "redacted_thinking", "data": "private-redacted"},
                    {"type": "text", "text": structured_text()},
                ]
            ),
        )

    result = await runtime(handle).generate(replace(generation_request(), profile=native_profile()))
    body = json.loads(requests[0].content)
    assert requests[0].url.path == "/v1/messages"
    assert requests[0].headers["x-api-key"] == SECRET
    assert requests[0].headers["anthropic-version"] == "2026-10-21"
    assert set(body) == {"model", "system", "messages", "max_tokens", "output_config"}
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["messages"][-1]["role"] == "user"
    assert result.execution.input_tokens == 60
    assert result.execution.output_tokens == 7
    assert result.execution.observed_provider_model_id == MODEL_ID
    assert result.generation.claims[0].text == "The synthetic limit is seven percent."
    assert "private" not in repr(result)


async def test_contextualization_uses_native_schema_and_shared_parser():
    requests = []

    def handle(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json=response_payload(
                content=[
                    {"type": "text", "text": '{"resolved_query":"synthetic resolved query"}'},
                ]
            ),
        )

    result = await runtime(handle).contextualize(
        ContextualizationRequest(
            question="synthetic question",
            history=(),
            profile=native_profile(),
        )
    )
    assert result.resolved_query == "synthetic resolved query"
    assert requests[0]["output_config"]["format"]["schema"]["required"] == ["resolved_query"]


@pytest.mark.parametrize(
    "change",
    [
        {"stop_reason": "max_tokens"},
        {"stop_reason": "refusal"},
        {"stop_reason": None},
        {"stop_details": {"type": "refusal", "explanation": "private refusal"}},
        {"stop_details": {"type": "unknown"}},
        {"model": "different-model"},
        {"role": "user"},
        {"type": "error"},
        {"stop_sequence": "unexpected"},
        {"content": [{"type": "tool_use", "input": "private"}]},
        {"content": [{"type": "unknown", "text": "private"}]},
        {"content": [{"type": [], "text": "private"}]},
        {"content": [{"type": {}, "text": "private"}]},
        {"content": [{"type": "text", "text": structured_text()}] * 2},
        {"content": [{"type": "text", "text": '{"schema_version":1,"claims":[]}'}]},
        {"content": [{"type": "text", "text": "not json private text"}]},
        {"content": [{"type": "text", "text": "[" * 2000 + "0" + "]" * 2000}]},
        {"usage": {"input_tokens": True, "output_tokens": 1}},
        {"usage": {"input_tokens": 1, "output_tokens": -1}},
        {"usage": {"input_tokens": 1, "output_tokens": 1, "cache_read_input_tokens": None}},
        {"usage": {}},
    ],
)
async def test_native_invalid_envelopes_and_output_are_safe_failures(change):
    selected = runtime(lambda request: httpx.Response(200, json=response_payload(**change)))
    with pytest.raises(GenerationProviderError) as caught:
        await selected.generate(replace(generation_request(), profile=native_profile()))
    assert caught.value.code in {"provider_invalid_response", "structured_output_invalid"}
    assert not caught.value.retryable
    formatted = "".join(traceback.format_exception(caught.value))
    assert "private refusal" not in formatted
    assert "not json private text" not in formatted
    assert SECRET not in formatted


@pytest.mark.parametrize(
    ("status", "code", "attempts"),
    [
        (401, "provider_authentication_failed", 1),
        (403, "provider_authentication_failed", 1),
        (400, "provider_invalid_response", 1),
        (302, "provider_invalid_response", 1),
        (429, "provider_rate_limited", 3),
        (529, "provider_unavailable", 3),
    ],
)
async def test_native_http_errors_use_only_bounded_configured_retries(status, code, attempts):
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(
            status,
            json={"error": {"message": "private vendor detail"}},
            headers={"Location": "https://other.example.test"},
        )

    with pytest.raises(GenerationProviderError) as caught:
        await runtime(handle, retries=2).generate(
            replace(generation_request(), profile=native_profile())
        )
    assert len(seen) == attempts
    assert caught.value.code == code
    assert "private vendor detail" not in "".join(traceback.format_exception(caught.value))


async def test_transport_timeout_does_not_claim_remote_termination():
    def handle(request):
        raise httpx.ReadTimeout("private request body", request=request)

    termination = GenerationTermination()
    with pytest.raises(GenerationProviderError, match="provider_timeout"):
        await tracked_generation_call(
            runtime(handle).generate(replace(generation_request(), profile=native_profile())),
            termination,
        )
    assert not termination.confirmed


async def test_cancellation_propagates_and_keeps_unconfirmed_attempt():
    async def handle(request):
        raise asyncio.CancelledError()

    termination = GenerationTermination()
    with pytest.raises(asyncio.CancelledError):
        await tracked_generation_call(
            runtime(handle).generate(replace(generation_request(), profile=native_profile())),
            termination,
        )
    assert not termination.confirmed


@pytest.mark.parametrize("model", [MODEL_ID, "different-model"])
async def test_health_is_exact_model_metadata_only(model):
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={"type": "model", "id": model})

    result = await runtime(handle).health()
    assert result.ready is (model == MODEL_ID)
    assert seen[0].method == "GET"
    assert seen[0].url.path == f"/v1/models/{MODEL_ID}"
    assert result.execution.input_tokens is None


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://provider.example.test/v1",
        "https://user:pass@provider.example.test/v1",
        "https://provider.example.test/v1?key=private",
        "https://provider.example.test/v1#private",
        "https://provider.example.test/other",
    ],
)
def test_native_endpoint_is_https_without_credentials_or_suffix(endpoint):
    with pytest.raises(ValueError):
        runtime(lambda request: httpx.Response(200), endpoint=endpoint)


async def test_excessive_envelope_nesting_is_a_safe_response_failure():
    body = '{"private":' + "[" * 2000 + "0" + "]" * 2000 + "}"
    with pytest.raises(GenerationProviderError, match="provider_invalid_response") as caught:
        await runtime(lambda request: httpx.Response(200, content=body)).generate(
            replace(generation_request(), profile=native_profile())
        )
    assert caught.value.__context__ is None


@pytest.mark.parametrize("parser", ["envelope", "grounded", "contextualization"])
async def test_decoder_recursion_failure_does_not_escape_provider_boundary(parser, monkeypatch):
    def recursive_failure(*args, **kwargs):
        raise RecursionError("synthetic private decoder detail")

    if parser == "envelope":
        monkeypatch.setattr(httpx.Response, "json", recursive_failure)
    else:
        attribute = (
            "parse_grounded_generation_v1" if parser == "grounded" else "parse_contextualization_v1"
        )
        monkeypatch.setattr(importlib.import_module(MODULE), attribute, recursive_failure)
    adapter = runtime(lambda request: httpx.Response(200, json=response_payload()))
    with pytest.raises(GenerationProviderError) as caught:
        if parser == "contextualization":
            await adapter.contextualize(
                ContextualizationRequest(
                    question="synthetic question", history=(), profile=native_profile()
                )
            )
        else:
            await adapter.generate(replace(generation_request(), profile=native_profile()))
    assert caught.value.__context__ is None
    assert "synthetic private decoder detail" not in "".join(
        traceback.format_exception(caught.value)
    )


async def test_cache_ttl_breakdown_does_not_duplicate_total_input():
    result = await runtime(
        lambda request: httpx.Response(
            200,
            json=response_payload(
                usage={
                    "input_tokens": 10,
                    "output_tokens": 7,
                    "cache_creation_input_tokens": 20,
                    "cache_read_input_tokens": 30,
                    "cache_creation": {
                        "ephemeral_5m_input_tokens": 12,
                        "ephemeral_1h_input_tokens": 8,
                    },
                }
            ),
        )
    ).generate(replace(generation_request(), profile=native_profile()))
    assert result.execution.input_tokens == 60


@pytest.mark.parametrize("ambiguous_first", [False, True])
async def test_success_only_settles_its_own_http_attempt(ambiguous_first):
    calls = 0

    def handle(request):
        nonlocal calls
        calls += 1
        if ambiguous_first and calls == 1:
            raise httpx.ReadTimeout("synthetic private transport detail", request=request)
        return httpx.Response(200, json=response_payload())

    termination = GenerationTermination()
    await tracked_generation_call(
        runtime(handle, retries=1).generate(
            replace(generation_request(), profile=native_profile())
        ),
        termination,
    )
    assert termination.confirmed is not ambiguous_first
