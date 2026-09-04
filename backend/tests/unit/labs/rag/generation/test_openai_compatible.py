import json
from uuid import UUID

import httpx
import pytest

from ai_workshop.labs.rag.generation.domain import (
    ContextPolicy,
    ContextualizationRequest,
    ConversationRole,
    ConversationTurn,
    GenerationProfile,
    GenerationRequest,
    GroundingEvidence,
)
from ai_workshop.labs.rag.generation.openai_compatible import (
    GenerationRuntimeResponseError,
    GenerationRuntimeUnavailableError,
    LocalOpenAICompatibleRuntime,
)


def profile() -> GenerationProfile:
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
    return httpx.AsyncClient(transport=handler)


def test_runtime_rejects_non_loopback_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        LocalOpenAICompatibleRuntime(base_url="https://models.example.com")


@pytest.mark.asyncio
async def test_health_requires_exact_registered_runtime_model() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json={"data": [{"id": "runtime/exact-model"}]})

    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            base_url="http://127.0.0.1:11434",
            client=client,
        )
        assert await runtime.health(profile()) is True


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
            base_url="http://localhost:11434",
            client=client,
        )
        assert await runtime.contextualize(request) == "위험 한도 7% 적용일"


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
            base_url="http://[::1]:11434",
            client=client,
        )
        result = await runtime.generate(request)

    assert result.schema_version == 1
    assert result.claims[0].evidence_ids == (evidence().evidence_id,)


@pytest.mark.asyncio
async def test_runtime_failure_does_not_expose_private_request_text() -> None:
    private_question = "비공개 고객의 위험 한도는?"

    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("private transport detail")

    request = ContextualizationRequest(
        question=private_question,
        history=(ConversationTurn(role=ConversationRole.USER, content="비공개 이전 질문"),),
        profile=profile(),
    )
    async with client_for(httpx.MockTransport(handler)) as client:
        runtime = LocalOpenAICompatibleRuntime(
            base_url="http://127.0.0.1:11434",
            client=client,
        )
        with pytest.raises(GenerationRuntimeUnavailableError) as caught:
            await runtime.contextualize(request)

    assert private_question not in str(caught.value)
    assert "private transport detail" not in str(caught.value)


@pytest.mark.asyncio
async def test_malformed_generation_response_uses_safe_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "draft secret"}}]})

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
            base_url="http://127.0.0.1:11434",
            client=client,
        )
        with pytest.raises(GenerationRuntimeResponseError) as caught:
            await runtime.generate(request)

    assert str(caught.value) == "The generation runtime returned an invalid response."
    assert "draft secret" not in str(caught.value)
