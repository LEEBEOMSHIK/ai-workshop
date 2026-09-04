from __future__ import annotations

import json
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest

from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.generation.domain import (
    ContextPolicy,
    ContextualizationRequest,
    ConversationRole,
    ConversationTurn,
    GenerationProfile,
    GenerationRequest,
    GroundingEvidence,
)
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.openai_responses import OpenAIResponsesRuntime
from ai_workshop.labs.rag.generation.structured_output import (
    CONTEXTUALIZATION_SCHEMA_V1,
    GROUNDED_GENERATION_SCHEMA_V1,
)

MODEL_ID = "gpt-synthetic-2026-01-01"
EVIDENCE_ID = UUID("30000000-0000-0000-0000-000000000001")


def deployment(**overrides: object) -> ModelDeploymentVersion:
    values: dict[str, object] = {
        "id": UUID("90000000-0000-0000-0000-000000000001"),
        "deployment_id": UUID("90000000-0000-0000-0000-000000000002"),
        "version": 3,
        "display_name": "Synthetic OpenAI runtime",
        "description": "Public synthetic fixture",
        "model_definition_id": UUID("20000000-0000-0000-0000-000000000001"),
        "provider": ProviderKind.OPENAI_RESPONSES,
        "location": ExecutionLocation.EXTERNAL,
        "allowed_environments": (DeploymentEnvironment.DEVELOPMENT,),
        "provider_model_id": MODEL_ID,
        "endpoint_ref": "openai-primary",
        "secret_ref": "openai-key",
        "capabilities": frozenset(
            {
                DeploymentCapability.STRUCTURED_OUTPUT,
                DeploymentCapability.CONTEXTUALIZATION,
                DeploymentCapability.TOKEN_ACCOUNTING,
            }
        ),
        "external_transfer": True,
        "transmitted_data_categories": ("question", "bounded_history", "evidence"),
        "data_processing_notice_ref": "public-openai-notice-v1",
        "timeout_seconds": 9.0,
        "max_retries": 2,
        "retry_backoff_seconds": 0.0,
        "healthcheck_enabled": True,
        "development_only": False,
        "created_by": UUID("90000000-0000-0000-0000-000000000003"),
        "created_at": datetime.now(UTC),
    }
    values.update(overrides)
    return ModelDeploymentVersion(**values)  # type: ignore[arg-type]


def profile(*, max_history_turns: int = 4) -> GenerationProfile:
    selected = deployment()
    return GenerationProfile(
        profile_id=UUID("10000000-0000-0000-0000-000000000001"),
        profile_name="external-generation",
        profile_version=1,
        model_id=selected.model_definition_id,
        model_name="registered-llm",
        model_version=2,
        runtime_model=MODEL_ID,
        prompt_ref="rag-answer-v1",
        context_prompt_ref="rag-contextualize-v1",
        context_policy=ContextPolicy(
            max_history_turns=max_history_turns,
            max_history_tokens=200,
        ),
        timeout_seconds=8.0,
        max_output_tokens=321,
        temperature=0.2,
        response_schema_version=1,
        deployment=selected,
    )


def evidence() -> GroundingEvidence:
    return GroundingEvidence(
        evidence_id=EVIDENCE_ID,
        text="The synthetic limit is seven percent.",
        document_id=UUID("40000000-0000-0000-0000-000000000001"),
        asset_version_id=UUID("50000000-0000-0000-0000-000000000001"),
        projection_id=UUID("60000000-0000-0000-0000-000000000001"),
        chunk_id=UUID("70000000-0000-0000-0000-000000000001"),
        element_id=UUID("80000000-0000-0000-0000-000000000001"),
        page=1,
        char_start=0,
        char_end=39,
        bbox=None,
    )


def generation_request(*, history: tuple[ConversationTurn, ...] = ()) -> GenerationRequest:
    return GenerationRequest(
        question="What is the synthetic limit?",
        resolved_query="synthetic limit",
        history=history,
        evidence=(evidence(),),
        profile=profile(),
        correlation_id="corr-public-synthetic",
    )


def structured_text() -> str:
    return json.dumps(
        {
            "schema_version": 1,
            "claims": [
                {
                    "text": "The synthetic limit is seven percent.",
                    "evidence_ids": [str(EVIDENCE_ID)],
                }
            ],
        }
    )


def response_payload(
    *,
    text: str | None = None,
    model: object = MODEL_ID,
    usage: object = None,
    status: object = "completed",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": "resp_synthetic",
        "object": "response",
        "status": status,
        "error": None,
        "incomplete_details": None,
        "model": model,
        "output": [],
        "usage": usage
        if usage is not None
        else {"input_tokens": 120, "output_tokens": 24, "total_tokens": 144},
    }
    if text is not None:
        payload["output_text"] = text
    return payload


@asynccontextmanager
async def transport_for(
    transport: httpx.MockTransport,
) -> AsyncIterator[httpx.MockTransport]:
    yield transport


def assert_sanitized(error: GenerationProviderError, *canaries: str) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None
    rendered = "".join(traceback.format_exception(error))
    for canary in canaries:
        assert canary not in str(error)
        assert canary not in rendered


def test_versioned_schemas_are_closed_and_require_nonempty_values() -> None:
    assert CONTEXTUALIZATION_SCHEMA_V1 == {
        "type": "object",
        "additionalProperties": False,
        "required": ["resolved_query"],
        "properties": {"resolved_query": {"type": "string"}},
    }
    assert GROUNDED_GENERATION_SCHEMA_V1["additionalProperties"] is False
    claims = GROUNDED_GENERATION_SCHEMA_V1["properties"]["claims"]
    assert claims["items"]["additionalProperties"] is False
    assert GROUNDED_GENERATION_SCHEMA_V1["properties"]["schema_version"] == {
        "type": "integer",
        "enum": [1],
    }


def test_wire_schemas_use_only_the_official_common_supported_subset() -> None:
    allowed_keywords = {
        "type",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "enum",
    }

    def assert_supported(schema: dict[str, object]) -> None:
        assert set(schema).issubset(allowed_keywords)
        properties = schema.get("properties")
        if isinstance(properties, dict):
            for child in properties.values():
                assert isinstance(child, dict)
                assert_supported(child)
        items = schema.get("items")
        if isinstance(items, dict):
            assert_supported(items)

    assert_supported(CONTEXTUALIZATION_SCHEMA_V1)
    assert_supported(GROUNDED_GENERATION_SCHEMA_V1)


@pytest.mark.asyncio
async def test_runtime_owns_and_closes_the_transport_client() -> None:
    requests = 0
    closes = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            request=request,
            json={"object": "list", "data": [{"id": MODEL_ID}]},
        )

    async def tracking_aclose() -> None:
        nonlocal closes
        closes += 1

    transport = httpx.MockTransport(handler)
    transport.aclose = tracking_aclose  # type: ignore[method-assign]
    runtime = OpenAIResponsesRuntime._for_test(
        deployment=deployment(),
        endpoint="https://api.example.invalid/v1",
        api_key="synthetic-secret",
        transport=transport,
    )

    result = await runtime.health()

    assert result.ready is True
    assert requests == 1
    assert closes == 1


@pytest.mark.asyncio
async def test_runtime_closes_the_owned_client_after_transport_failure() -> None:
    closes = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private-transport-detail", request=request)

    async def tracking_aclose() -> None:
        nonlocal closes
        closes += 1

    transport = httpx.MockTransport(handler)
    transport.aclose = tracking_aclose  # type: ignore[method-assign]
    runtime = OpenAIResponsesRuntime._for_test(
        deployment=deployment(),
        endpoint="https://api.example.invalid/v1",
        api_key="synthetic-secret",
        transport=transport,
    )

    with pytest.raises(GenerationProviderError) as caught:
        await runtime.health()

    assert caught.value.code == "provider_invalid_response"
    assert closes == 1


@pytest.mark.parametrize(
    "endpoint",
    [
        "ftp://api.example.invalid/v1",
        "https://user:password@api.example.invalid/v1",
        "https://api.example.invalid/v1?tenant=private",
        "https://api.example.invalid/v1#fragment",
        "//api.example.invalid/v1",
    ],
)
def test_runtime_rejects_malformed_or_credentialed_endpoints(endpoint: str) -> None:
    with pytest.raises(ValueError):
        OpenAIResponsesRuntime(
            deployment=deployment(), endpoint=endpoint, api_key="synthetic-secret"
        )


@pytest.mark.asyncio
async def test_generate_sends_exact_stateless_strict_request_and_normalizes_usage() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=response_payload(text=structured_text()))

    async with transport_for(httpx.MockTransport(handler)) as transport:
        runtime = OpenAIResponsesRuntime._for_test(
            deployment=deployment(),
            endpoint="https://api.example.invalid/v1/",
            api_key="synthetic-secret",
            transport=transport,
        )
        result = await runtime.generate(generation_request())

    assert len(requests) == 1
    sent = requests[0]
    payload = json.loads(sent.content)
    assert sent.method == "POST"
    assert str(sent.url) == "https://api.example.invalid/v1/responses"
    assert sent.headers["Authorization"] == "Bearer synthetic-secret"
    assert payload["model"] == MODEL_ID
    assert payload["instructions"]
    assert isinstance(payload["input"], list)
    assert payload["text"]["format"] == {
        "type": "json_schema",
        "name": "rag_grounded_generation_v1",
        "strict": True,
        "schema": GROUNDED_GENERATION_SCHEMA_V1,
    }
    assert payload["store"] is False
    assert payload["max_output_tokens"] == 321
    assert payload["temperature"] == 0.2
    for forbidden in ("conversation", "previous_response_id", "metadata", "tools"):
        assert forbidden not in payload
    assert result.generation.claims[0].evidence_ids == (EVIDENCE_ID,)
    assert result.execution.provider_model_id == MODEL_ID
    assert result.execution.input_tokens == 120
    assert result.execution.output_tokens == 24


@pytest.mark.asyncio
async def test_contextualize_uses_origin_url_and_only_newest_profile_bounded_history() -> None:
    seen_payload: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/responses"
        seen_payload.update(json.loads(request.content))
        return httpx.Response(
            200,
            json=response_payload(text='{"resolved_query":"standalone synthetic query"}'),
        )

    history = tuple(
        ConversationTurn(role=ConversationRole.USER, content=f"history-{index}")
        for index in range(25)
    )
    request = ContextualizationRequest(
        question="current synthetic question",
        history=history,
        profile=profile(max_history_turns=3),
    )
    async with transport_for(httpx.MockTransport(handler)) as transport:
        runtime = OpenAIResponsesRuntime._for_test(
            deployment=deployment(),
            endpoint="https://api.example.invalid",
            api_key="synthetic-secret",
            transport=transport,
        )
        result = await runtime.contextualize(request)

    assert result.resolved_query == "standalone synthetic query"
    assert seen_payload["text"]["format"]["schema"] == CONTEXTUALIZATION_SCHEMA_V1
    assert seen_payload["store"] is False
    input_items = seen_payload["input"]
    rendered = json.dumps(input_items)
    assert "history-21" not in rendered
    assert "history-22" in rendered
    assert "history-24" in rendered
    assert "current synthetic question" in rendered


@pytest.mark.parametrize("variant", ["top_level", "assistant_item"])
@pytest.mark.asyncio
async def test_accepts_each_supported_single_output_text_representation(variant: str) -> None:
    payload = response_payload()
    if variant == "top_level":
        payload["output_text"] = structured_text()
    else:
        payload["output"] = [
            {
                "id": "msg_synthetic",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {"type": "output_text", "text": structured_text(), "annotations": []}
                ],
            }
        ]

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with transport_for(httpx.MockTransport(handler)) as transport:
        result = await OpenAIResponsesRuntime._for_test(
            deployment=deployment(),
            endpoint="https://api.example.invalid/v1",
            api_key="synthetic-secret",
            transport=transport,
        ).generate(generation_request())

    assert result.generation.claims[0].text == "The synthetic limit is seven percent."


@pytest.mark.parametrize(
    "payload",
    [
        response_payload(),
        {**response_payload(text=structured_text()), "error": {"code": "server_error"}},
        {**response_payload(text=structured_text()), "status": "incomplete"},
        {
            **response_payload(),
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "refusal", "refusal": "cannot comply"}],
                }
            ],
        },
        {
            **response_payload(text=structured_text()),
            "output": [
                {
                    "type": "message",
                    "status": "completed",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": structured_text()}],
                }
            ],
        },
    ],
)
@pytest.mark.asyncio
async def test_rejects_missing_error_incomplete_refusal_or_multiple_output(payload: object) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with transport_for(httpx.MockTransport(handler)) as transport:
        runtime = OpenAIResponsesRuntime._for_test(
            deployment=deployment(),
            endpoint="https://api.example.invalid/v1",
            api_key="synthetic-secret",
            transport=transport,
        )
        with pytest.raises(GenerationProviderError) as caught:
            await runtime.generate(generation_request())

    assert (caught.value.code, caught.value.retryable) == (
        "provider_invalid_response",
        False,
    )


@pytest.mark.parametrize("field", ["object", "error", "incomplete_details"])
@pytest.mark.asyncio
async def test_rejects_missing_required_response_envelope_fields(field: str) -> None:
    payload = response_payload(text=structured_text())
    del payload[field]

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with transport_for(httpx.MockTransport(handler)) as transport:
        runtime = OpenAIResponsesRuntime._for_test(
            deployment=deployment(),
            endpoint="https://api.example.invalid/v1",
            api_key="synthetic-secret",
            transport=transport,
        )
        with pytest.raises(GenerationProviderError) as caught:
            await runtime.generate(generation_request())

    assert caught.value.code == "provider_invalid_response"


@pytest.mark.parametrize(
    "structured",
    [
        "not-json",
        {"schema_version": 2, "claims": [{"text": "x", "evidence_ids": [str(EVIDENCE_ID)]}]},
        {"schema_version": 1, "claims": []},
        {
            "schema_version": 1,
            "claims": [{"text": "", "evidence_ids": [str(EVIDENCE_ID)]}],
        },
        {
            "schema_version": 1,
            "claims": [{"text": "x", "evidence_ids": []}],
        },
        {
            "schema_version": 1,
            "claims": [{"text": "x", "evidence_ids": [str(EVIDENCE_ID)]}],
            "extra": True,
        },
        {
            "schema_version": 1,
            "claims": [
                {"text": "x", "evidence_ids": [str(EVIDENCE_ID)], "extra": True}
            ],
        },
        {
            "schema_version": 1,
            "claims": [
                {
                    "text": "x",
                    "evidence_ids": [str(EVIDENCE_ID), str(EVIDENCE_ID)],
                }
            ],
        },
        {
            "schema_version": 1,
            "claims": [
                {
                    "text": "x",
                    "evidence_ids": ["30000000-0000-0000-0000-000000000099"],
                }
            ],
        },
    ],
)
@pytest.mark.asyncio
async def test_rejects_malformed_or_schema_invalid_structured_generation(
    structured: object,
) -> None:
    text = structured if isinstance(structured, str) else json.dumps(structured)

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload(text=text))

    async with transport_for(httpx.MockTransport(handler)) as transport:
        runtime = OpenAIResponsesRuntime._for_test(
            deployment=deployment(),
            endpoint="https://api.example.invalid/v1",
            api_key="synthetic-secret",
            transport=transport,
        )
        with pytest.raises(GenerationProviderError) as caught:
            await runtime.generate(generation_request())

    assert (caught.value.code, caught.value.retryable) == (
        "structured_output_invalid",
        False,
    )


@pytest.mark.parametrize(
    "text",
    [
        "not-json",
        "{}",
        '{"resolved_query":""}',
        '{"resolved_query":"valid","extra":true}',
    ],
)
@pytest.mark.asyncio
async def test_rejects_invalid_contextualization_schema(text: str) -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response_payload(text=text))

    request = ContextualizationRequest(question="question", history=(), profile=profile())
    async with transport_for(httpx.MockTransport(handler)) as transport:
        runtime = OpenAIResponsesRuntime._for_test(
            deployment=deployment(),
            endpoint="https://api.example.invalid/v1",
            api_key="synthetic-secret",
            transport=transport,
        )
        with pytest.raises(GenerationProviderError) as caught:
            await runtime.contextualize(request)

    assert caught.value.code == "structured_output_invalid"


@pytest.mark.parametrize(
    "response_model,usage",
    [
        ("gpt-synthetic-alias", {"input_tokens": 1, "output_tokens": 2}),
        (MODEL_ID, None),
        (MODEL_ID, {"input_tokens": -1, "output_tokens": 2}),
        (MODEL_ID, {"input_tokens": True, "output_tokens": 2}),
        (MODEL_ID, {"input_tokens": 1.5, "output_tokens": 2}),
        (MODEL_ID, {"input_tokens": 1, "output_tokens": "2"}),
    ],
)
@pytest.mark.asyncio
async def test_rejects_model_mismatch_or_invalid_exact_usage(
    response_model: object,
    usage: object,
) -> None:
    payload = response_payload(text=structured_text(), model=response_model)
    payload["usage"] = usage

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with transport_for(httpx.MockTransport(handler)) as transport:
        runtime = OpenAIResponsesRuntime._for_test(
            deployment=deployment(),
            endpoint="https://api.example.invalid/v1",
            api_key="synthetic-secret",
            transport=transport,
        )
        with pytest.raises(GenerationProviderError) as caught:
            await runtime.generate(generation_request())

    assert caught.value.code == "provider_invalid_response"


@pytest.mark.parametrize(
    ("status", "code", "retryable", "expected_attempts"),
    [
        (401, "provider_authentication_failed", False, 1),
        (403, "provider_authentication_failed", False, 1),
        (429, "provider_rate_limited", True, 3),
        (500, "provider_invalid_response", False, 1),
    ],
)
@pytest.mark.asyncio
async def test_maps_http_errors_and_only_retries_rate_limits(
    status: int,
    code: str,
    retryable: bool,
    expected_attempts: int,
) -> None:
    attempts = 0

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(status, json={"error": {"message": "raw-private"}})

    async with transport_for(httpx.MockTransport(handler)) as transport:
        runtime = OpenAIResponsesRuntime._for_test(
            deployment=deployment(),
            endpoint="https://api.example.invalid/v1",
            api_key="synthetic-secret",
            transport=transport,
        )
        with pytest.raises(GenerationProviderError) as caught:
            await runtime.generate(generation_request())

    assert (caught.value.code, caught.value.retryable) == (code, retryable)
    assert attempts == expected_attempts


@pytest.mark.parametrize(
    ("failure", "code", "retryable", "expected_attempts"),
    [
        ("timeout", "provider_timeout", True, 3),
        ("connect", "provider_invalid_response", False, 1),
    ],
)
@pytest.mark.asyncio
async def test_only_retries_timeout_transport_failures(
    failure: str,
    code: str,
    retryable: bool,
    expected_attempts: int,
) -> None:
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if failure == "timeout":
            raise httpx.ReadTimeout("raw-private", request=request)
        raise httpx.ConnectError("raw-private", request=request)

    async with transport_for(httpx.MockTransport(handler)) as transport:
        runtime = OpenAIResponsesRuntime._for_test(
            deployment=deployment(),
            endpoint="https://api.example.invalid/v1",
            api_key="synthetic-secret",
            transport=transport,
        )
        with pytest.raises(GenerationProviderError) as caught:
            await runtime.generate(generation_request())

    assert (caught.value.code, caught.value.retryable) == (code, retryable)
    assert attempts == expected_attempts


@pytest.mark.asyncio
async def test_redirect_is_not_followed() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(307, headers={"location": "https://escape.invalid"})

    async with transport_for(httpx.MockTransport(handler)) as transport:
        runtime = OpenAIResponsesRuntime._for_test(
            deployment=deployment(),
            endpoint="https://api.example.invalid/v1",
            api_key="synthetic-secret",
            transport=transport,
        )
        with pytest.raises(GenerationProviderError) as caught:
            await runtime.generate(generation_request())

    assert caught.value.code == "provider_invalid_response"
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_private_transport_and_response_data_are_removed_from_exception_graph(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    endpoint = "https://endpoint-canary.invalid/v1"
    secret = "CANARY-SECRET"
    question = "CANARY-QUESTION"
    history_text = "CANARY-HISTORY"
    raw = "CANARY-RAW-RESPONSE"
    attempts = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ReadTimeout("CANARY-TRANSPORT", request=request)
        return httpx.Response(200, content=raw, headers={"content-type": "application/json"})

    request = replace(
        generation_request(
            history=(ConversationTurn(role=ConversationRole.USER, content=history_text),)
        ),
        question=question,
    )
    async with transport_for(httpx.MockTransport(handler)) as transport:
        runtime = OpenAIResponsesRuntime._for_test(
            deployment=replace(deployment(), max_retries=1),
            endpoint=endpoint,
            api_key=secret,
            transport=transport,
        )
        with pytest.raises(GenerationProviderError) as caught:
            await runtime.generate(request)

    assert caught.value.code == "provider_invalid_response"
    assert_sanitized(
        caught.value,
        endpoint,
        secret,
        question,
        history_text,
        raw,
        "CANARY-TRANSPORT",
        "Authorization",
    )
    assert caplog.records == []
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.asyncio
async def test_health_is_authenticated_and_requires_the_exact_model() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"object": "list", "data": [{"id": MODEL_ID}]})

    async with transport_for(httpx.MockTransport(handler)) as transport:
        result = await OpenAIResponsesRuntime._for_test(
            deployment=deployment(),
            endpoint="https://api.example.invalid/v1",
            api_key="synthetic-secret",
            transport=transport,
        ).health()

    assert result.ready is True
    assert result.observed_provider_model_id == MODEL_ID
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/v1/models"
    assert requests[0].headers["Authorization"] == "Bearer synthetic-secret"


@pytest.mark.asyncio
async def test_health_does_not_accept_a_nearby_model_alias() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"object": "list", "data": [{"id": "gpt-synthetic"}]},
        )

    async with transport_for(httpx.MockTransport(handler)) as transport:
        result = await OpenAIResponsesRuntime._for_test(
            deployment=deployment(),
            endpoint="https://api.example.invalid/v1",
            api_key="synthetic-secret",
            transport=transport,
        ).health()

    assert result.ready is False
    assert result.observed_provider_model_id is None
