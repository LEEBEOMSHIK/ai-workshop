import json
import traceback
from contextlib import aclosing
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest

from ai_workshop.config import Settings
from ai_workshop.labs.rag.deployments.domain import (
    DeploymentCapability,
    DeploymentEnvironment,
    ExecutionLocation,
    ModelDeploymentVersion,
    ProviderKind,
)
from ai_workshop.labs.rag.documents.domain import TableCellLocation
from ai_workshop.labs.rag.generation.citation_validation import CitationValidator
from ai_workshop.labs.rag.generation.domain import (
    ContextPolicy,
    ContextualizationRequest,
    ConversationRole,
    ConversationTurn,
    GenerationProfile,
    GenerationRequest,
    GenerationStatus,
    GroundingEvidence,
)
from ai_workshop.labs.rag.generation.evidence_payload import evidence_payload
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.openai_compatible import (
    LocalOpenAICompatibleRuntime,
)
from ai_workshop.labs.rag.generation.runtime_resolver import (
    GenerationRuntimeResolver,
    builtin_generation_runtime_factories,
)
from ai_workshop.labs.rag.policies.domain import PolicyDecision


def local_deployment(
    *, location: ExecutionLocation = ExecutionLocation.LOCAL
) -> ModelDeploymentVersion:
    return ModelDeploymentVersion(
        id=UUID("90000000-0000-0000-0000-000000000001"),
        deployment_id=UUID("90000000-0000-0000-0000-000000000002"),
        version=1,
        display_name="Local exact runtime",
        description="Synthetic runtime fixture",
        model_definition_id=UUID("20000000-0000-0000-0000-000000000001"),
        provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
        location=location,
        allowed_environments=(DeploymentEnvironment.DEVELOPMENT,),
        provider_model_id="runtime/exact-model",
        endpoint_ref="local-runtime",
        secret_ref=None,
        capabilities=frozenset({DeploymentCapability.STRUCTURED_OUTPUT}),
        external_transfer=False,
        transmitted_data_categories=(),
        data_processing_notice_ref=None,
        timeout_seconds=12.0,
        max_retries=0,
        retry_backoff_seconds=0.0,
        healthcheck_enabled=True,
        development_only=False,
        created_by=UUID("90000000-0000-0000-0000-000000000003"),
        created_at=datetime.now(UTC),
    )


def profile() -> GenerationProfile:
    deployment = local_deployment()
    return GenerationProfile(
        profile_id=UUID("10000000-0000-0000-0000-000000000001"),
        profile_name="local-generation",
        profile_version=1,
        model_id=UUID("20000000-0000-0000-0000-000000000001"),
        model_name="registered-llm",
        model_version=2,
        runtime_model="runtime/exact-model",
        prompt_ref="rag-answer-v1",
        context_prompt_ref="rag-contextualize-v1",
        context_policy=ContextPolicy(max_history_turns=4, max_history_tokens=200),
        timeout_seconds=12.0,
        max_output_tokens=300,
        temperature=0.2,
        response_schema_version=1,
        deployment=deployment,
    )


def evidence() -> GroundingEvidence:
    return GroundingEvidence(
        evidence_id=UUID("30000000-0000-0000-0000-000000000001"),
        text="위험 한도는 순자산의 7%입니다.",
        document_id=UUID("40000000-0000-0000-0000-000000000001"),
        asset_version_id=UUID("50000000-0000-0000-0000-000000000001"),
        projection_id=UUID("60000000-0000-0000-0000-000000000001"),
        chunk_id=UUID("70000000-0000-0000-0000-000000000001"),
        element_id=UUID("80000000-0000-0000-0000-000000000001"),
        page=None,
        char_start=0,
        char_end=20,
        bbox=None,
    )


def client_for(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=handler,
        trust_env=False,
        follow_redirects=False,
    )


def assert_sanitized_error(
    error: GenerationProviderError,
    *forbidden_canaries: str,
) -> None:
    assert error.__cause__ is None
    assert error.__context__ is None
    rendered = "".join(traceback.format_exception(error))
    for canary in forbidden_canaries:
        assert canary not in str(error)
        assert canary not in rendered


def test_runtime_rejects_non_loopback_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        LocalOpenAICompatibleRuntime(
            deployment=local_deployment(),
            endpoint="https://models.example.com",
        )


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://127.0.0.1/model",
        "http://user:password@127.0.0.1:11434",
        "http://127.0.0.1:11434/#fragment",
        "http://2130706433:11434",
        "http://0x7f000001:11434",
        "http://localhost.example:11434",
    ],
)
def test_local_runtime_rejects_unsafe_or_ambiguous_urls(base_url: str) -> None:
    with pytest.raises(ValueError):
        LocalOpenAICompatibleRuntime(
            deployment=local_deployment(),
            endpoint=base_url,
        )


def test_on_premise_runtime_accepts_a_server_allowlisted_http_endpoint() -> None:
    runtime = LocalOpenAICompatibleRuntime(
        deployment=local_deployment(location=ExecutionLocation.ON_PREMISE),
        endpoint="https://models.internal.example:8443",
    )

    assert runtime.base_url == "https://models.internal.example:8443"


@pytest.mark.asyncio
async def test_internally_owned_client_does_not_trust_proxy_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client_options: dict[str, object] = {}

    class RecordingClient:
        def __init__(self, **options: object) -> None:
            client_options.update(options)

        async def __aenter__(self) -> "RecordingClient":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def request(self, method: str, url: str, **_options: object) -> httpx.Response:
            request = httpx.Request(method, url)
            return httpx.Response(
                200,
                request=request,
                json={"data": [{"id": "runtime/exact-model"}]},
            )

    monkeypatch.setattr(httpx, "AsyncClient", RecordingClient)
    runtime = LocalOpenAICompatibleRuntime(
        deployment=local_deployment(),
        endpoint="http://127.0.0.1:11434",
    )

    result = await runtime.health()
    assert result.ready is True
    assert client_options["trust_env"] is False
    assert client_options["follow_redirects"] is False


@pytest.mark.asyncio
async def test_health_requires_exact_registered_runtime_model_without_logging(
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "runtime/exact-model"}]})

    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=local_deployment(),
            endpoint="http://127.0.0.1:11434",
            client=client,
        )
        result = await runtime.health()

    assert result.ready is True
    assert result.observed_provider_model_id == "runtime/exact-model"
    assert result.execution.provider_model_id == "runtime/exact-model"
    assert result.execution.deployment_version_id == profile().deployment.id
    assert caplog.records == []
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.asyncio
async def test_contextualize_sends_exact_model_and_returns_standalone_query() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "runtime/exact-model"
        assert payload["temperature"] == 0.2
        assert "그 한도는 언제 적용돼?" in payload["messages"][1]["content"]
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": '{"resolved_query":"위험 한도 7% 적용일"}'}}
                ]
            },
        )

    request = ContextualizationRequest(
        question="그 한도는 언제 적용돼?",
        history=(
            ConversationTurn(role=ConversationRole.USER, content="위험 한도는 얼마야?"),
            ConversationTurn(
                role=ConversationRole.ASSISTANT,
                content="순자산의 7%입니다.",
                validation_token="signed",
            ),
        ),
        profile=profile(),
    )
    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=local_deployment(),
            endpoint="http://localhost:11434",
            client=client,
        )
        result = await runtime.contextualize(request)

    assert result.resolved_query == "위험 한도 7% 적용일"
    assert result.execution.provider_model_id == "runtime/exact-model"


@pytest.mark.asyncio
async def test_generate_parses_versioned_claim_schema() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["model"] == "runtime/exact-model"
        assert payload["max_tokens"] == 300
        assert str(evidence().evidence_id) in payload["messages"][1]["content"]
        content = {
            "schema_version": 1,
            "claims": [
                {
                    "text": "위험 한도는 순자산의 7%입니다.",
                    "evidence_ids": [str(evidence().evidence_id)],
                }
            ],
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content)}}]},
        )

    request = GenerationRequest(
        question="위험 한도는?",
        resolved_query="위험 한도",
        history=(),
        evidence=(evidence(),),
        profile=profile(),
        correlation_id="corr-safe",
    )
    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=local_deployment(),
            endpoint="http://[::1]:11434",
            client=client,
        )
        result = await runtime.generate(request)

    assert result.generation.schema_version == 1
    assert result.generation.claims[0].evidence_ids == (evidence().evidence_id,)
    assert result.execution.input_tokens is None
    assert result.execution.output_tokens is None


@pytest.mark.parametrize(
    ("exception_kind", "expected_code"),
    [
        ("connect", "deployment_not_ready"),
        ("timeout", "provider_timeout"),
    ],
)
@pytest.mark.asyncio
async def test_transport_failure_discards_exception_graph_and_private_state(
    exception_kind: str,
    expected_code: str,
    caplog: pytest.LogCaptureFixture,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_question = "CANARY-QUESTION"
    private_history = "CANARY-HISTORY"
    private_secret = "CANARY-SECRET"
    private_transport = "CANARY-TRANSPORT"
    private_endpoint = "http://127.0.0.1:11434"

    async def handler(request: httpx.Request) -> httpx.Response:
        if exception_kind == "timeout":
            raise httpx.ReadTimeout(private_transport, request=request)
        raise httpx.ConnectError(private_transport, request=request)

    request = ContextualizationRequest(
        question=private_question,
        history=(ConversationTurn(role=ConversationRole.USER, content=private_history),),
        profile=profile(),
    )
    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=local_deployment(),
            endpoint=private_endpoint,
            api_key=private_secret,
            client=client,
        )
        with pytest.raises(GenerationProviderError) as caught:
            await runtime.contextualize(request)

    assert caught.value.code == expected_code
    assert_sanitized_error(
        caught.value,
        private_question,
        private_history,
        private_secret,
        private_transport,
        private_endpoint,
    )
    assert caplog.records == []
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.asyncio
async def test_provider_json_decode_failure_discards_raw_response_exception() -> None:
    raw_response = "CANARY-RAW-PROVIDER-RESPONSE"

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=raw_response,
            headers={"content-type": "application/json"},
        )

    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=local_deployment(),
            endpoint="http://127.0.0.1:11434",
            client=client,
        )
        with pytest.raises(GenerationProviderError) as caught:
            await runtime.health()

    assert caught.value.code == "provider_invalid_response"
    assert_sanitized_error(caught.value, raw_response)


@pytest.mark.asyncio
async def test_malformed_generation_response_uses_safe_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "CANARY-RAW-GENERATION-RESPONSE"}}
                ]
            },
        )

    request = GenerationRequest(
        question="질문",
        resolved_query="질문",
        history=(),
        evidence=(evidence(),),
        profile=profile(),
        correlation_id="corr-safe",
    )
    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=local_deployment(),
            endpoint="http://127.0.0.1:11434",
            client=client,
        )
        with pytest.raises(GenerationProviderError) as caught:
            await runtime.generate(request)

    assert str(caught.value) == "provider_invalid_response"
    assert_sanitized_error(caught.value, "CANARY-RAW-GENERATION-RESPONSE")


@pytest.mark.asyncio
async def test_redirect_response_is_rejected_without_following_location() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            302,
            headers={"location": "https://external.example.invalid/v1/models"},
        )

    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=local_deployment(),
            endpoint="http://127.0.0.1:11434",
            client=client,
        )
        with pytest.raises(GenerationProviderError) as caught:
            await runtime.health()

    assert caught.value.code == "provider_invalid_response"
    assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("contextual", [False, True])
async def test_empty_claims_are_abstention_only_for_contextual_prompt(contextual):
    from dataclasses import replace

    from ai_workshop.labs.rag.models.context_evidence import EvidenceBudget

    async def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {
            "content": '{"schema_version":1,"claims":[]}'}}]})

    selected = profile()
    if contextual:
        selected = replace(selected, prompt_ref="rag-answer-v2",
                           evidence_budget=EvidenceBudget(8, 32, 12000))
    request = GenerationRequest(question="synthetic question", resolved_query="query",
        history=(), evidence=(evidence(),), profile=selected, correlation_id="synthetic")
    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(deployment=local_deployment(),
            endpoint="http://127.0.0.1:11434", client=client)
        if contextual:
            result = await runtime.generate(request)
            assert result.status == "insufficient_evidence"
            assert result.generation is None
        else:
            with pytest.raises(GenerationProviderError):
                await runtime.generate(request)


def schema2_profile():
    from ai_workshop.labs.rag.models.context_evidence import EvidenceBudget

    return replace(profile(), response_schema_version=2, prompt_ref="rag-answer-v2",
                   evidence_budget=EvidenceBudget(8, 32, 12000))


def schema2_answer():
    return {"schema_version": 2, "status": "answered", "claims": [
        {"text": "Synthetic supported claim.", "evidence_ids": [str(evidence().evidence_id)]},
    ]}


def ollama_completion(content, *, choice_overrides=None, message_overrides=None):
    # Synthetic OpenAI-compatible Ollama envelope, without contacting a server.
    message = {"role": "assistant", "content": content}
    message.update(message_overrides or {})
    choice = {"index": 0, "message": message, "finish_reason": "stop"}
    choice.update(choice_overrides or {})
    return {"id": "synthetic", "object": "chat.completion", "model": "runtime/exact-model",
            "choices": [choice]}


async def schema2_call(payload, *, operation="generate", check_request=None):
    requests = []

    async def handler(request):
        requests.append(request)
        return httpx.Response(200, json=payload)

    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=local_deployment(), endpoint="http://127.0.0.1:11434", client=client,
        )
        selected = schema2_profile()
        if operation == "contextualize":
            result = await runtime.contextualize(ContextualizationRequest("question", (), selected))
        else:
            result = await runtime.generate(GenerationRequest(
                "question", "resolved", (), (evidence(),), selected, "synthetic",
            ))
    assert len(requests) == 1
    assert requests[0].url.path == "/v1/chat/completions"
    if check_request:
        check_request(json.loads(requests[0].content))
    return result


@pytest.mark.parametrize("status", ["answered", "insufficient_evidence"])
async def test_ollama_schema2_status_claims_and_wire_contract(status):
    content = schema2_answer()
    content["status"] = status
    if status == "insufficient_evidence":
        content["claims"] = []

    def check_request(payload):
        assert payload["model"] == "runtime/exact-model"
        assert payload["response_format"] == {"type": "json_object"}
        assert '"status":"answered"' in payload["messages"][0]["content"]
        assert '"insufficient_evidence"' in payload["messages"][0]["content"]
        assert json.loads(payload["messages"][1]["content"])["schema_version"] == 2

    result = await schema2_call(ollama_completion(json.dumps(content)), check_request=check_request)
    assert result.status == GenerationStatus(status)
    if status == "answered":
        assert result.generation.schema_version == 2
        assert result.generation.claims[0].evidence_ids == (evidence().evidence_id,)
    else:
        assert result.generation is None


@pytest.mark.parametrize("change", [
    {"status": None}, {"status": "unknown"}, {"status": "insufficient_evidence"},
    {"claims": []}, {"extra": "CANARY-PRIVATE"}, {"schema_version": True},
    {"schema_version": 2.0}, {"claims": [{"text": 7, "evidence_ids": []}]},
    {"claims": [{"text": " ", "evidence_ids": [str(evidence().evidence_id)]}]},
    {"claims": [{"text": "claim", "evidence_ids": []}]},
    {"claims": [{"text": "claim", "evidence_ids": [None]}]},
    {"claims": [{"text": "claim", "evidence_ids": ["not-a-uuid"]}]},
    {"claims": [{"text": "claim", "evidence_ids": [str(evidence().evidence_id)], "extra": 1}]},
])
async def test_ollama_schema2_rejects_invalid_claim_contract(change):
    content = schema2_answer() | change
    with pytest.raises(GenerationProviderError, match="provider_invalid_response") as caught:
        await schema2_call(ollama_completion(json.dumps(content)))
    assert_sanitized_error(caught.value, "CANARY-PRIVATE")


@pytest.mark.parametrize("content", [
    '{"schema_version":2,"claims":[]}',
    '{"schema_version":1,"claims":[]}',
    '{"schema_version":2,"status":"insufficient_evidence"}',
    '{"schema_version":2,"status":"insufficient_evidence","claims":[],"claims":[]}',
    '{"schema_version":2,"status":"insufficient_evidence","claims":[],"extra":NaN}',
    '{"schema_version":2,"status":"insufficient_evidence","claims":[]',
    '```json\n{"schema_version":2,"status":"insufficient_evidence","claims":[]}\n```',
    json.dumps(schema2_answer()).replace('"text":', '"text":"ignored", "text":'),
])
async def test_ollama_schema2_strict_json_rejects_malformed_or_legacy_abstention(content):
    with pytest.raises(GenerationProviderError, match="provider_invalid_response") as caught:
        await schema2_call(ollama_completion(content))
    assert_sanitized_error(caught.value, content)


@pytest.mark.parametrize("operation", ["generate", "contextualize"])
@pytest.mark.parametrize(
    "finish_reason", [None, "length", "content_filter", "tool_calls", "missing"],
)
async def test_ollama_schema2_requires_explicit_normal_completion(operation, finish_reason):
    content = json.dumps(
        schema2_answer() if operation == "generate" else {"resolved_query": "query"},
    )
    payload = ollama_completion(content, choice_overrides={"finish_reason": finish_reason})
    if finish_reason == "missing":
        del payload["choices"][0]["finish_reason"]
    with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
        await schema2_call(payload, operation=operation)


@pytest.mark.parametrize("message", [
    {"role": "tool"}, {"thinking": "CANARY-PRIVATE"},
    {"reasoning": "CANARY-PRIVATE"}, {"reasoning_content": "CANARY-PRIVATE"},
    {"tool_calls": [{"function": {"name": "synthetic", "arguments": "CANARY-PRIVATE"}}]},
    {"function_call": {"name": "synthetic", "arguments": "CANARY-PRIVATE"}},
    {"refusal": "CANARY-PRIVATE"},
])
async def test_ollama_schema2_rejects_private_reasoning_and_tool_outputs(message, caplog, capsys):
    with pytest.raises(GenerationProviderError, match="provider_invalid_response") as caught:
        await schema2_call(ollama_completion(
            json.dumps(schema2_answer()), message_overrides=message,
        ))
    assert_sanitized_error(caught.value, "CANARY-PRIVATE")
    reason = "role" if "role" in message else "unsupported_output"
    rejection_records = [r for r in caplog.records if not r.name.endswith(".response_diagnostics")]
    assert [record.getMessage() for record in rejection_records] == [
        f"provider_response_rejected stage=message reason={reason} correlation_id=unavailable",
    ]
    assert all(record.exc_info is None for record in caplog.records)
    assert "CANARY-PRIVATE" not in caplog.text
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("content", [
    '{"resolved_query":"first","resolved_query":"second"}',
    '{"resolved_query":"query","thinking":"CANARY-PRIVATE"}',
    '{"resolved_query":42}', '{"resolved_query":" "}',
])
async def test_ollama_schema2_contextualization_is_strict(content):
    with pytest.raises(GenerationProviderError, match="provider_invalid_response") as caught:
        await schema2_call(ollama_completion(content), operation="contextualize")
    assert_sanitized_error(caught.value, "CANARY-PRIVATE")


async def test_ollama_schema2_contextualization_normal_completion():
    result = await schema2_call(ollama_completion('{"resolved_query":"synthetic query"}'),
                               operation="contextualize")
    assert result.resolved_query == "synthetic query"


async def test_schema3_is_rejected_before_http_request():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(500)

    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(deployment=local_deployment(),
            endpoint="http://127.0.0.1:11434", client=client)
        request = GenerationRequest("question", "resolved", (), (evidence(),),
            replace(profile(), response_schema_version=3), "synthetic")
        with pytest.raises(GenerationProviderError, match="generation_schema_not_supported"):
            await runtime.generate(request)
    assert calls == []


async def test_health_rejects_different_model_as_not_ready():
    async def handler(request):
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "runtime/different-model"}]})

    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(deployment=local_deployment(),
            endpoint="http://127.0.0.1:11434/", client=client)
        result = await runtime.health()
    assert result.ready is False
    assert result.observed_provider_model_id is None


async def dialect_call(payload, *, operation="generate", dialect="ollama", selected=None):
    requests = []

    async def handler(request):
        requests.append(request)
        if isinstance(payload, str):
            return httpx.Response(
                200, content=payload, headers={"content-type": "application/json"},
            )
        return httpx.Response(200, json=payload)

    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=local_deployment(), endpoint="http://127.0.0.1:11434",
            client=client, dialect=dialect,
        )
        selected = selected or schema2_profile()
        if operation == "contextualize":
            result = await runtime.contextualize(ContextualizationRequest("question", (), selected))
        else:
            result = await runtime.generate(GenerationRequest(
                "question", "resolved", (), (evidence(),), selected, "synthetic",
            ))
    assert len(requests) == 1
    return result, json.loads(requests[0].content)


@pytest.mark.parametrize("status", ["answered", "insufficient_evidence"])
async def test_explicit_ollama_discards_reasoning_metadata(status, caplog, capsys):
    content = schema2_answer() | {"status": status}
    if status == "insufficient_evidence":
        content["claims"] = []
    result, sent = await dialect_call(ollama_completion(
        json.dumps(content), message_overrides={"reasoning": "SYNTHETIC-PRIVATE-CANARY"},
    ))
    assert result.status.value == status
    assert "SYNTHETIC-PRIVATE-CANARY" not in repr(result)
    assert "reasoning_effort" not in sent
    assert sent["max_tokens"] == schema2_profile().max_output_tokens
    if status == "answered":
        assert result.generation.claims[0].evidence_ids == (evidence().evidence_id,)
    else:
        assert result.generation is None
    assert len(caplog.records) == 1
    assert caplog.records[0].name.endswith(".response_diagnostics")
    assert "SYNTHETIC-PRIVATE-CANARY" not in caplog.text
    assert "Synthetic supported claim" not in caplog.text
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


@pytest.mark.parametrize("budget", [64, 512])
async def test_ollama_contextualize_requests_no_thinking_without_increasing_budget(budget):
    selected = replace(schema2_profile(), max_output_tokens=budget)
    result, sent = await dialect_call(ollama_completion(
        '{"resolved_query":"synthetic standalone query"}',
        message_overrides={"reasoning": "SYNTHETIC-PRIVATE-CANARY"},
    ), operation="contextualize", selected=selected)
    assert result.resolved_query == "synthetic standalone query"
    assert "SYNTHETIC-PRIVATE-CANARY" not in repr(result)
    assert sent["reasoning_effort"] == "none"
    assert sent["max_tokens"] == budget
    assert 'one short standalone search query' in sent["messages"][0]["content"]
    assert "think" not in sent and "options" not in sent


@pytest.mark.parametrize("dialect,schema", [("openai", 2), ("openai", 1), ("ollama", 1)])
async def test_ollama_context_policy_does_not_change_other_modes(dialect, schema):
    selected = replace(profile(), response_schema_version=schema)
    result, sent = await dialect_call(ollama_completion('{"resolved_query":"query"}'),
        operation="contextualize", dialect=dialect, selected=selected)
    assert result.resolved_query == "query"
    assert "reasoning_effort" not in sent
    assert 'one short standalone search query' not in sent["messages"][0]["content"]
    assert sent["max_tokens"] == selected.max_output_tokens


@pytest.mark.parametrize("reasoning", [None, True, 4, [], {"text": "SYNTHETIC-PRIVATE-CANARY"}])
async def test_ollama_reasoning_metadata_requires_string(reasoning):
    with pytest.raises(GenerationProviderError, match="provider_invalid_response") as caught:
        await dialect_call(ollama_completion(json.dumps(schema2_answer()),
            message_overrides={"reasoning": reasoning}))
    assert_sanitized_error(caught.value, "SYNTHETIC-PRIVATE-CANARY")


@pytest.mark.parametrize("operation", ["generate", "contextualize"])
async def test_ollama_reasoning_does_not_rescue_truncation_or_retry(operation):
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json=ollama_completion(
            json.dumps(schema2_answer()) if operation == "generate" else '{"resolved_query":"q"}',
            choice_overrides={"finish_reason": "length"},
            message_overrides={"reasoning": "SYNTHETIC-PRIVATE-CANARY"},
        ))

    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=replace(local_deployment(), max_retries=2),
            endpoint="http://127.0.0.1:11434", client=client, dialect="ollama",
        )
        with pytest.raises(GenerationProviderError, match="provider_invalid_response") as caught:
            if operation == "generate":
                await runtime.generate(GenerationRequest(
                    "q", "q", (), (evidence(),), schema2_profile(), "synthetic",
                ))
            else:
                await runtime.contextualize(ContextualizationRequest("q", (), schema2_profile()))
    assert len(calls) == 1
    assert_sanitized_error(caught.value, "SYNTHETIC-PRIVATE-CANARY")


@pytest.mark.parametrize("message", [
    {"thinking": "SYNTHETIC-PRIVATE-CANARY"},
    {"reasoning_content": "SYNTHETIC-PRIVATE-CANARY"},
    {"unknown": "SYNTHETIC-PRIVATE-CANARY"},
    {"tool_calls": [{"function": {"name": "tool", "arguments": "secret"}}]},
])
async def test_ollama_accepts_no_other_message_extensions(message):
    with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
        await dialect_call(ollama_completion(json.dumps(schema2_answer()),
            message_overrides={"reasoning": "synthetic"} | message))


@pytest.mark.parametrize("content", [
    json.dumps(schema2_answer() | {"reasoning": "SYNTHETIC-PRIVATE-CANARY"}),
    json.dumps(schema2_answer() | {"status": "insufficient_evidence"}),
    json.dumps(schema2_answer()).replace('"text":', '"text":"ignored","text":'),
    json.dumps(schema2_answer()).replace(str(evidence().evidence_id), "invalid-uuid"),
])
async def test_ollama_metadata_never_weakens_content_schema(content, caplog, capsys):
    payload = ollama_completion(content,
        message_overrides={"reasoning": "SYNTHETIC-PRIVATE-CANARY"})
    with pytest.raises(GenerationProviderError, match="provider_invalid_response") as caught:
        await dialect_call(payload)
    assert_sanitized_error(caught.value, "SYNTHETIC-PRIVATE-CANARY")
    rejection_records = [r for r in caplog.records if not r.name.endswith(".response_diagnostics")]
    assert len(rejection_records) == 1
    message = rejection_records[0].getMessage().split(" categories=", 1)[0]
    assert message.split(" violations=", 1)[0] in {
        f"provider_response_rejected stage={stage} reason={reason} correlation_id=unavailable"
        for stage, reason in (("answer_schema", "extra_fields"), ("answer_contract", "invalid"),
                              ("answer_json", "invalid"), ("evidence_id", "invalid"))
    }
    assert caplog.records[0].exc_info is None
    assert "SYNTHETIC-PRIVATE-CANARY" not in caplog.text
    captured = capsys.readouterr()
    assert captured.out == captured.err == ""


async def test_ollama_rejects_duplicate_envelope_fields():
    payload = json.dumps(ollama_completion(json.dumps(schema2_answer()),
        message_overrides={"reasoning": "synthetic"}))
    payload = payload.replace('"reasoning":', '"reasoning":"ignored","reasoning":')
    with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
        await dialect_call(payload)


def test_unknown_dialect_is_rejected_before_network():
    with pytest.raises(ValueError, match="dialect"):
        LocalOpenAICompatibleRuntime(deployment=local_deployment(),
            endpoint="http://127.0.0.1:11434", dialect="unverified")


@pytest.mark.parametrize("content", [
    '{"resolved_query":"first","resolved_query":"second"}',
    '{"resolved_query":"query","reasoning":"SYNTHETIC-PRIVATE-CANARY"}',
    '{"resolved_query":42}',
])
async def test_explicit_ollama_context_content_remains_strict(content):
    payload = ollama_completion(content,
        message_overrides={"reasoning": "SYNTHETIC-PRIVATE-CANARY"})
    with pytest.raises(GenerationProviderError, match="provider_invalid_response") as caught:
        await dialect_call(payload, operation="contextualize")
    assert_sanitized_error(caught.value, "SYNTHETIC-PRIVATE-CANARY")


def test_builtin_factory_keeps_default_http_dialect():
    from ai_workshop.labs.rag.generation.runtime_resolver import (
        builtin_generation_runtime_factories,
    )

    runtime = builtin_generation_runtime_factories()[ProviderKind.LOCAL_OPENAI_COMPATIBLE](
        local_deployment(), "http://127.0.0.1:11434", None,
    )
    assert isinstance(runtime, LocalOpenAICompatibleRuntime)
    assert runtime.dialect == "openai"


@pytest.mark.parametrize("entrypoint", ["factory", "search", "health"])
@pytest.mark.parametrize("dialect", [None, "openai", "ollama"])
@pytest.mark.parametrize("schema", [1, 2])
async def test_endpoint_dialect_reaches_context_request_without_inference(
    monkeypatch, entrypoint, dialect, schema,
):
    from sqlalchemy.ext.asyncio import AsyncSession

    from ai_workshop.labs.rag.deployments.service import get_deployment_health_service
    from ai_workshop.labs.rag.search import api as search_api

    configured = {} if dialect is None else {"local-runtime": dialect}
    settings = Settings(secret_key="x" * 32, _env_file=None,
                        provider_endpoint_refs={"local-runtime": "http://127.0.0.1:11434"},
                        provider_endpoint_dialects=configured)
    # Even an Ollama-looking URL/model must stay generic unless explicitly selected.
    selected_deployment = replace(local_deployment(), provider_model_id="ollama-model")
    selected_profile = replace(profile(), deployment=selected_deployment,
                               runtime_model="ollama-model", response_schema_version=schema)
    policy = PolicyDecision(True, None, None, ())
    client = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(search_api, "create_elasticsearch", lambda _settings: client)
    async with AsyncSession() as session:
        if entrypoint == "search":
            async with aclosing(search_api.get_search_service(
                session, settings, object(), SimpleNamespace(runtime_factory=None), None,
            )) as dependency:
                service = await anext(dependency)
                resolver = service.generation_runtime_resolver
                runtime = resolver.resolve(selected_deployment, policy).adapter
            client.close.assert_awaited_once()
        elif entrypoint == "health":
            service = get_deployment_health_service(session, settings, None)
            runtime = service._runtime_resolver.resolve(selected_deployment, policy).adapter
        else:
            factories = builtin_generation_runtime_factories(
                provider_endpoint_dialects=settings.provider_endpoint_dialects,
            )
            resolver = GenerationRuntimeResolver(environment="test",
                endpoint_refs=settings.provider_endpoint_refs, secret_refs={}, factories=factories)
            runtime = resolver.resolve(selected_deployment, policy).adapter

    sent = []
    async def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=ollama_completion('{"resolved_query":"synthetic query"}'))

    async with client_for(httpx.MockTransport(handler)) as http_client:
        runtime.client = http_client
        result = await runtime.contextualize(
            ContextualizationRequest("follow up", (), selected_profile)
        )
    assert result.resolved_query == "synthetic query"
    assert len(sent) == 1
    assert sent[0]["model"] == "ollama-model"
    assert sent[0]["max_tokens"] == selected_profile.max_output_tokens
    if dialect == "ollama" and schema == 2:
        assert sent[0]["reasoning_effort"] == "none"
        assert "one short standalone search query" in sent[0]["messages"][0]["content"]
    else:
        assert "reasoning_effort" not in sent[0]
        assert "one short standalone search query" not in sent[0]["messages"][0]["content"]


def test_endpoint_dialect_does_not_replace_other_provider_factory():
    from ai_workshop.labs.rag.generation.openai_responses import OpenAIResponsesRuntime

    selected = replace(local_deployment(), provider=ProviderKind.OPENAI_RESPONSES,
                       location=ExecutionLocation.EXTERNAL, external_transfer=True,
                       transmitted_data_categories=("question",),
                       data_processing_notice_ref="synthetic-notice-v1",
                       secret_ref="synthetic-secret")
    factories = builtin_generation_runtime_factories(
        provider_endpoint_dialects={"local-runtime": "ollama"},
    )
    runtime = factories[ProviderKind.OPENAI_RESPONSES](
        selected, "https://api.example.test", "synthetic-secret",
    )
    assert isinstance(runtime, OpenAIResponsesRuntime)


@pytest.mark.parametrize("operation", ["generate", "contextualize"])
@pytest.mark.parametrize("dialect", ["openai", "ollama"])
@pytest.mark.parametrize("schema_version", [1, 2])
async def test_json_schema_wire_contract_is_scoped_to_explicit_ollama_schema2(
    operation, dialect, schema_version,
):
    from ai_workshop.labs.rag.generation.openai_compatible import _AnswerV2, _QueryV2

    selected = replace(schema2_profile(), response_schema_version=schema_version)
    content = schema2_answer() | {"schema_version": schema_version}
    if schema_version == 1:
        del content["status"]
    if operation == "contextualize":
        content = {"resolved_query": "synthetic query"}
    result, sent = await dialect_call(ollama_completion(json.dumps(content)),
        operation=operation, dialect=dialect, selected=selected)
    if dialect == "ollama" and schema_version == 2:
        contract = _QueryV2 if operation == "contextualize" else _AnswerV2
        assert sent["response_format"] == {
            "type": "json_schema", "json_schema": {"schema": contract.model_json_schema()},
        }
        schema = sent["response_format"]["json_schema"]["schema"]
        objects = [schema] if operation == "contextualize" else schema["anyOf"]
        assert all(item["additionalProperties"] is False for item in objects)
    else:
        assert sent["response_format"] == {"type": "json_object"}
    assert sent["model"] == selected.runtime_model
    assert sent["max_tokens"] == selected.max_output_tokens
    assert sent["temperature"] == selected.temperature
    if operation == "contextualize":
        assert result.resolved_query == "synthetic query"
    else:
        assert result.generation.schema_version == schema_version
        assert result.generation.claims[0].evidence_ids == (evidence().evidence_id,)


@pytest.mark.parametrize("operation", ["generate", "contextualize"])
async def test_unsupported_json_schema_fails_without_fallback_retry_or_secret_leak(
    operation, caplog,
):
    sent = []
    private = "SYNTHETIC-UNSUPPORTED-SCHEMA-SECRET"

    async def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(400, json={"error": {"message": private}})

    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=replace(local_deployment(), max_retries=2),
            endpoint="http://127.0.0.1:11434", api_key=private, client=client, dialect="ollama",
        )
        with pytest.raises(GenerationProviderError) as caught:
            if operation == "contextualize":
                await runtime.contextualize(
                    ContextualizationRequest(private, (), schema2_profile()),
                )
            else:
                await runtime.generate(GenerationRequest(
                    private, private, (), (evidence(),), schema2_profile(), "synthetic",
                ))
    assert len(sent) == 1
    assert sent[0]["response_format"]["type"] == "json_schema"
    assert caught.value.code == "provider_invalid_response"
    assert caught.value.retryable is False
    assert_sanitized_error(caught.value, private)
    assert private not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_wire_answer_schema_encodes_exact_version_and_both_status_claim_bounds():
    _, sent = await dialect_call(ollama_completion(json.dumps(schema2_answer())))
    schema = sent["response_format"]["json_schema"]["schema"]
    # Full object alternatives avoid the grammar converter's properties/anyOf mixing limit.
    assert "properties" not in schema
    assert len(schema["anyOf"]) == 2
    branches = {item["properties"]["status"]["const"]: item for item in schema["anyOf"]}
    assert set(branches) == {"answered", "insufficient_evidence"}
    for branch in branches.values():
        assert branch["type"] == "object"
        assert branch["additionalProperties"] is False
        assert set(branch["required"]) == {"schema_version", "status", "claims"}
        assert branch["properties"]["schema_version"]["const"] == 2
        assert branch["properties"]["schema_version"]["type"] == "integer"
        assert branch["properties"]["claims"]["items"] == {"$ref": "#/$defs/_ClaimV2"}
    assert branches["answered"]["properties"]["claims"]["minItems"] == 1
    assert "maxItems" not in branches["answered"]["properties"]["claims"]
    assert branches["insufficient_evidence"]["properties"]["claims"]["maxItems"] == 0
    claim = schema["$defs"]["_ClaimV2"]
    assert claim["additionalProperties"] is False
    assert claim["properties"]["evidence_ids"]["minItems"] == 1
    assert not {"if", "then", "else", "not", "allOf"}.intersection(schema)


@pytest.mark.parametrize("dialect", ["openai", "ollama"])
@pytest.mark.parametrize("version", [1, 2])
async def test_answer_contract_prompt_is_scoped_and_explicit(dialect, version):
    answer = schema2_answer() | {"schema_version": version}
    if version == 1:
        del answer["status"]
    _, sent = await dialect_call(ollama_completion(json.dumps(answer)), dialect=dialect,
        selected=replace(schema2_profile(), response_schema_version=version))
    prompt = sent["messages"][0]["content"]
    if dialect == "ollama" and version == 2:
        assert "schema_version must be exactly 2" in prompt
        assert 'status "answered": claims must contain at least 1 item' in prompt
        assert 'status "insufficient_evidence": claims must contain exactly 0 items' in prompt
    else:
        assert "schema_version must be exactly" not in prompt


@pytest.mark.parametrize("dialect,version,effort", [
    ("openai", 1, None), ("openai", 2, None),
    ("ollama", 1, None), ("ollama", 2, None), ("ollama", 2, "none"),
])
async def test_http_context_compaction_preserves_evidence_and_citation_boundary(
    dialect, version, effort,
):
    first = replace(
        evidence(), text='  발행일: 2026-09-03\n원문 "공백" 보존  ',
        section_path=("합성 보고서", "발행 정보"), ordinal=3, page=2,
        bbox=(1.0, 2.0, 30.0, 40.0), source_kind="table_cell", source_part="table:1",
        table_cell=TableCellLocation(2, 3, 1, 2),
    )
    second = replace(
        first, evidence_id=UUID(int=32), element_id=UUID(int=82), text="후속 설명",
        ordinal=4, char_start=21, char_end=26, table_cell=TableCellLocation(2, 4),
    )
    third = replace(
        evidence(), evidence_id=UUID(int=33), document_id=UUID(int=43),
        asset_version_id=UUID(int=53), projection_id=UUID(int=63), chunk_id=UUID(int=73),
    )
    original = (first, second, third)
    original_payload = evidence_payload(original, contextual=True)
    selected = replace(schema2_profile(), response_schema_version=version,
                       answer_reasoning_effort=effort)
    history = (ConversationTurn(role=ConversationRole.USER, content="이전 질문"),)
    sent = []
    responses = [
        ("발행일은 2026-09-03입니다.", str(first.evidence_id)),
        ("발행일은 2026-09-03입니다.", str(UUID(int=999))),
        ("발행일은 2026-09-04입니다.", str(first.evidence_id)),
    ]

    async def handler(request):
        claim, citation = responses[len(sent)]
        sent.append(json.loads(request.content))
        answer = {"schema_version": version, "claims": [{
            "text": claim, "evidence_ids": [citation],
        }]}
        if version == 2:
            answer["status"] = "answered"
        return httpx.Response(200, json=ollama_completion(json.dumps(answer)))

    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=local_deployment(), endpoint="http://127.0.0.1:11434",
            client=client, dialect=dialect,
        )
        outcomes = []
        for _ in responses:
            result = await runtime.generate(GenerationRequest(
                "발행일?", "합성 보고서 발행일?", history, original, selected, "synthetic",
            ))
            assert result.generation is not None
            outcomes.append(CitationValidator().validate(
                result.generation, allowed_evidence=original,
            ))

    raw = sent[0]["messages"][1]["content"]
    payload = json.loads(raw)
    assert payload["context_notice"] == original_payload[0]["context_notice"]
    assert raw == json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    assert payload["question"] == "발행일?"
    assert payload["resolved_query"] == "합성 보고서 발행일?"
    assert payload["history"] == [{"role": "user", "content": "이전 질문"}]
    restored = []
    identity_fields = ("document_id", "asset_version_id", "projection_id", "chunk_id")
    for raw_item in payload["evidence"]:
        item = payload["evidence_groups"][raw_item["group_ref"]] | {
            key: value for key, value in raw_item.items() if key != "group_ref"
        }
        assert not set(identity_fields).intersection(item)
        assert "context_notice" not in item
        restored.append(item | dict(zip(identity_fields, item["group_id"].split(":"), strict=True))
                        | {"context_notice": payload["context_notice"]})
    assert restored == original_payload
    assert evidence_payload(original, contextual=True) == original_payload
    assert outcomes[0].status is GenerationStatus.ANSWERED
    assert outcomes[0].citations[0].evidence_ids == (first.evidence_id,)
    assert outcomes[1].reason_codes == ("evidence_not_allowed",)
    assert outcomes[2].reason_codes == ("exact_value_not_supported",)


@pytest.mark.parametrize("dialect", ["openai", "ollama"])
async def test_http_compaction_keeps_noncontextual_wire_unchanged(dialect):
    answer = {"schema_version": 1, "claims": [{
        "text": "위험 한도는 7%입니다.", "evidence_ids": [str(evidence().evidence_id)],
    }]}
    _, sent = await dialect_call(
        ollama_completion(json.dumps(answer)), dialect=dialect, selected=profile(),
    )
    assert sent["messages"][1]["content"] == json.dumps({
        "schema_version": 1, "question": "question", "resolved_query": "resolved",
        "history": [], "evidence": [{"evidence_id": str(evidence().evidence_id),
                                     "text": evidence().text}],
    }, ensure_ascii=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["generate", "contextualize"])
@pytest.mark.parametrize("finish,broken", [("stop", False), ("length", False), ("stop", True)])
async def test_http_usage_survives_success_and_rejected_content(operation, finish, broken, caplog):
    selected = replace(schema2_profile(), max_output_tokens=512)
    content = (json.dumps(schema2_answer()) if operation == "generate"
               else '{"resolved_query":"synthetic query"}')
    if broken:
        content = "SYNTHETIC-BODY-SECRET"
    payload = ollama_completion(
        content, choice_overrides={"finish_reason": finish},
        message_overrides={"reasoning": "SYNTHETIC-REASONING-SECRET"},
    )
    payload["usage"] = {"prompt_tokens": 123, "completion_tokens": 456,
                        "total_tokens": 579, "completion_tokens_details": {"reasoning_tokens": 400}}
    if finish == "stop" and not broken:
        result, sent = await dialect_call(payload, operation=operation, selected=selected)
        execution = result.execution
        assert sent["max_tokens"] == 512
        assert sent.get("reasoning_effort") == ("none" if operation == "contextualize" else None)
    else:
        with pytest.raises(GenerationProviderError) as caught:
            await dialect_call(payload, operation=operation, selected=selected)
        assert caught.value.code == "provider_invalid_response"
        assert caught.value.retryable is False
        execution = getattr(caught.value, "execution", None)
        assert execution is not None
    assert (execution.input_tokens, execution.output_tokens) == (123, 456)
    records = [r for r in caplog.records if r.name.endswith(".response_diagnostics")]
    assert len(records) == 1
    message = records[0].getMessage()
    assert f"operation={operation}" in message and f"finish_reason={finish}" in message
    assert "input_tokens=123 output_tokens=456 total_tokens=579 reasoning_tokens=400" in message
    assert all(r.exc_info is None for r in records)
    assert "SYNTHETIC-BODY-SECRET" not in caplog.text
    assert "SYNTHETIC-REASONING-SECRET" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [None, True, -1, 1.5, "SYNTHETIC-USAGE-SECRET", [], {}, 2**31])
@pytest.mark.parametrize("finish", ["stop", "length"])
async def test_http_malformed_usage_never_masks_completion(bad, finish, caplog):
    payload = ollama_completion(
        json.dumps(schema2_answer()), choice_overrides={"finish_reason": finish},
    )
    payload["usage"] = {"prompt_tokens": bad, "completion_tokens": 0,
                        "total_tokens": bad, "completion_tokens_details": {"reasoning_tokens": bad}}
    if finish == "stop":
        result, _ = await dialect_call(payload)
        execution = result.execution
    else:
        with pytest.raises(GenerationProviderError) as caught:
            await dialect_call(payload)
        assert caught.value.code == "provider_invalid_response"
        execution = getattr(caught.value, "execution", None)
        assert execution is not None
    assert execution.input_tokens is None
    assert execution.output_tokens == 0
    assert "SYNTHETIC-USAGE-SECRET" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("usage", [None, [], "SYNTHETIC-USAGE-SECRET"])
async def test_http_unknown_finish_and_usage_are_redacted(usage, caplog):
    payload = ollama_completion(json.dumps(schema2_answer()),
                                choice_overrides={"finish_reason": "SYNTHETIC-FINISH-SECRET"})
    payload["usage"] = usage
    with pytest.raises(GenerationProviderError) as caught:
        await dialect_call(payload)
    execution = getattr(caught.value, "execution", None)
    assert execution is not None
    assert execution.input_tokens is None and execution.output_tokens is None
    assert "finish_reason=other" in caplog.text
    assert "SYNTHETIC" not in caplog.text


async def test_answer_reasoning_opt_in_changes_only_answer_request_effort():
    response = ollama_completion(json.dumps({"schema_version": 2, "status": "answered",
        "claims": [{"text": "synthetic supported claim",
                    "evidence_ids": [str(evidence().evidence_id)]}]}))
    original = replace(schema2_profile(), max_output_tokens=512)
    _, baseline = await dialect_call(response, selected=original)
    selected = replace(original, answer_reasoning_effort="none")
    result, opted = await dialect_call(response, selected=selected)
    assert opted.pop("reasoning_effort") == "none"
    assert opted == baseline
    assert "reasoning_effort" not in baseline
    assert result.status is GenerationStatus.ANSWERED
    assert result.generation.claims[0].evidence_ids == (evidence().evidence_id,)
    assert selected.max_output_tokens == 512
    assert original.answer_reasoning_effort is None


async def test_answer_reasoning_opt_in_preserves_rewrite_request():
    response = ollama_completion('{"resolved_query":"synthetic query"}')
    original = replace(schema2_profile(), max_output_tokens=512)
    _, baseline = await dialect_call(response, operation="contextualize", selected=original)
    _, opted = await dialect_call(response, operation="contextualize",
                                 selected=replace(original, answer_reasoning_effort="none"))
    assert opted == baseline
    assert opted["reasoning_effort"] == "none"


async def test_answer_reasoning_opt_in_rejects_openai_dialect_without_http():
    async def handler(request):
        pytest.fail("Unsupported answer reasoning must fail before HTTP")
    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(deployment=local_deployment(),
            endpoint="http://127.0.0.1:11434", client=client, dialect="openai")
        selected = replace(schema2_profile(), answer_reasoning_effort="none")
        with pytest.raises(GenerationProviderError, match="generation_schema_not_supported"):
            await runtime.generate(GenerationRequest("question", "resolved", (),
                (evidence(),), selected, "synthetic"))


@pytest.mark.parametrize("value", [True, False, 0, [], {}, "low", "NONE"])
def test_answer_reasoning_runtime_profile_rejects_invalid_values(value):
    with pytest.raises(ValueError, match="answer reasoning"):
        replace(schema2_profile(), answer_reasoning_effort=value)


@pytest.mark.parametrize("schema", [1, 3])
def test_answer_reasoning_runtime_profile_requires_schema2(schema):
    with pytest.raises(ValueError, match="answer reasoning"):
        replace(schema2_profile(), response_schema_version=schema, answer_reasoning_effort="none")


@pytest.mark.parametrize("finish,content", [
    ("length", '{"schema_version":2,"status":"insufficient_evidence","claims":[]}'),
    ("stop", '{"schema_version":2,"status":"answered","claims":[]}'),
    ("stop", '{"schema_version":2,"status":"insufficient_evidence","claims":[],"extra":1}'),
    ("stop", '{"schema_version":2'),
])
async def test_answer_reasoning_opt_in_preserves_strict_failures(finish, content):
    calls = []
    completion = ollama_completion(content, choice_overrides={"finish_reason": finish})
    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json=completion)
    async with client_for(httpx.MockTransport(handler)) as client:
        exact = replace(local_deployment(), timeout_seconds=360, max_retries=0)
        runtime = LocalOpenAICompatibleRuntime(deployment=exact,
            endpoint="http://127.0.0.1:11434", client=client, dialect="ollama")
        selected = replace(schema2_profile(), deployment=exact, timeout_seconds=360,
                           max_output_tokens=512, answer_reasoning_effort="none")
        with pytest.raises(GenerationProviderError, match="provider_invalid_response") as caught:
            await runtime.generate(GenerationRequest("question", "resolved", (),
                (evidence(),), selected, "synthetic"))
        assert caught.value.retryable is False
    assert len(calls) == 1
    assert json.loads(calls[0].content)["max_tokens"] == 512
    assert calls[0].extensions["timeout"]["read"] == 360
