import json
import traceback
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
from ai_workshop.labs.rag.generation.openai_compatible import (
    LocalOpenAICompatibleRuntime,
)


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
