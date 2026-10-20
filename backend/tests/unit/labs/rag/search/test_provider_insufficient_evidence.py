import json
from dataclasses import replace
from uuid import UUID

import httpx
import pytest

from ai_workshop.labs.rag.deployments.domain import ExecutionLocation, ProviderKind
from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    GenerationRequest,
    GenerationStatus,
)
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    ProviderContextualizationResult,
    ProviderExecutionMetadata,
    ProviderGenerationResult,
    ProviderHealthResult,
)
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.generation.openai_compatible import LocalOpenAICompatibleRuntime
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget
from ai_workshop.labs.rag.highlighting.domain import EvidenceSource
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.labs.rag.retrieval.domain import (
    FusedHit,
    ResolvedSearchScope,
    SelectedDocumentIdentity,
    SparseHit,
)
from ai_workshop.labs.rag.search.schemas import ConversationTurnRequest, SearchRequest
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.highlighting.test_evidence_selector import _source
from tests.unit.labs.rag.search.test_generation_policy_gate import (
    ACTOR_ID,
    CONFIGURATION_ID,
    INSTALLATION_POLICY_ID,
    WORKSPACE_ID,
    _approval,
    _configuration,
    _deployment,
    _service,
)


class InsufficientRuntime:
    def __init__(self, mismatch: str | None) -> None:
        deployment = _deployment()
        self.execution = ProviderExecutionMetadata(
            deployment.provider, deployment.provider_model_id, deployment.id, 7, 3, 10
        )
        self.mismatch = mismatch

    async def health(self) -> ProviderHealthResult:
        return ProviderHealthResult(True, self.execution.provider_model_id, self.execution)

    async def contextualize(
        self, request: ContextualizationRequest
    ) -> ProviderContextualizationResult:
        assert request.history
        return ProviderContextualizationResult(
            "synthetic fact", replace(self.execution, input_tokens=5, output_tokens=2, latency_ms=6)
        )

    async def generate(self, request: GenerationRequest) -> ProviderGenerationResult:
        assert request.evidence
        execution = self.execution
        if self.mismatch == "model":
            execution = replace(execution, provider_model_id="wrong-model")
        elif self.mismatch == "deployment":
            execution = replace(execution, deployment_version_id=UUID(int=42))
        return ProviderGenerationResult(
            None, execution, status=GenerationStatus.INSUFFICIENT_EVIDENCE
        )


class OneSourceRetriever:
    async def search_sparse(
        self, *, query: str, scope: ResolvedSearchScope, **_kwargs: object
    ) -> tuple[SparseHit, ...]:
        assert query == "synthetic fact"
        assert WORKSPACE_ID in scope.workspace_ids
        return (SparseHit(_source(1, "synthetic fact").chunk, 1, 1.0),)


class ActiveScopeResolver:
    async def resolve(self, **_kwargs: object) -> ResolvedSearchScope:
        source = _source(1, "synthetic fact")
        chunk = source.chunk
        return ResolvedSearchScope(
            (WORKSPACE_ID,),
            (),
            asset_version_ids=(chunk.asset_version_id,),
            index_build_ids=(chunk.index_build_id,),
            authorized_documents=(SelectedDocumentIdentity(
                source.document_id, chunk.asset_version_id,
                chunk.projection_id, chunk.index_build_id,
            ),),
        )


class OneSourceResolver:
    async def resolve(
        self, *, hits: tuple[FusedHit, ...], **_kwargs: object
    ) -> tuple[EvidenceSource, ...]:
        assert len(hits) == 1
        return (_source(1, "synthetic fact"),)


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", [None, "model", "deployment"])
async def test_provider_abstention_preserves_retrieval_and_checks_identity(
    mismatch: str | None,
) -> None:
    configuration = replace(
        _configuration(approval=_approval()),
        generation_runtime=InsufficientRuntime(mismatch),
    )
    approval = _approval()
    service, _scope, _runtime, audits = _service(
        configuration=configuration,
        decision=PolicyDecision(
            True,
            None,
            INSTALLATION_POLICY_ID,
            tuple(item.policy_version_id for item in approval.workspace_policies),
            workspace_policy_snapshots=tuple(
                (item.workspace_id, item.policy_version_id) for item in approval.workspace_policies
            ),
        ),
    )
    service.sparse_retriever = OneSourceRetriever()
    service.scope_resolver = ActiveScopeResolver()
    service.source_resolver = OneSourceResolver()
    service.turn_signer = ConversationTurnSigner(b"synthetic-test-signing-key-32-bytes")
    request = SearchRequest(
        query="synthetic fact",
        configuration_id=CONFIGURATION_ID,
        workspace_ids=[WORKSPACE_ID],
        experimental=True,
        history=[ConversationTurnRequest(role="user", content="earlier synthetic question")],
    )

    if mismatch is not None:
        with pytest.raises(AppError) as caught:
            await service.search(actor_id=ACTOR_ID, request=request)
        assert caught.value.code == "provider_invalid_response"
        assert len(audits.audits) == 1
        assert audits.audits[0].status == "failed"
        assert audits.audits[0].safe_error_code == "provider_invalid_response"
        return

    result = await service.search(actor_id=ACTOR_ID, request=request)
    assert result.selection.answer is not None
    assert result.selection.answer.excerpt == "synthetic fact"
    assert result.retrieved_evidence_ids == (UUID("50000000-0000-0000-0000-000000000001"),)
    outcome = result.generation
    assert outcome.status is GenerationStatus.INSUFFICIENT_EVIDENCE
    assert outcome.text is None
    assert outcome.citations == ()
    assert outcome.reason_codes == ("evidence_content_insufficient",)
    assert outcome.turn_id is None
    assert outcome.validation_token is None
    assert outcome.execution is not None
    assert outcome.execution.model_name == "OpenAI synthetic model"
    assert len(audits.audits) == audits.commits == 1
    audit = audits.audits[0]
    assert audit.status == "allowed"
    assert audit.safe_error_code is None
    assert audit.evidence_ids == result.retrieved_evidence_ids
    assert (audit.input_tokens, audit.output_tokens, audit.latency_ms) == (12, 5, 16)


@pytest.mark.parametrize("outcome", ["answered", "wrong_citation", "insufficient_evidence"])
async def test_local_http_schema2_reaches_existing_evidence_and_citation_gate(
    outcome: str,
) -> None:
    calls: list[dict] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            assert request.url.path == "/v1/models"
            return httpx.Response(200, json={"data": [{"id": deployment.provider_model_id}]})
        body = json.loads(request.content)
        assert request.url.path == "/v1/chat/completions"
        payload = json.loads(body["messages"][1]["content"])
        calls.append(payload)
        evidence_id = payload["evidence"][0]["evidence_id"]
        content = {
            "schema_version": 2,
            "status": "insufficient_evidence" if outcome == "insufficient_evidence" else "answered",
            "claims": [] if outcome == "insufficient_evidence" else [{
                "text": "synthetic fact",
                "evidence_ids": [str(UUID(int=42)) if outcome == "wrong_citation" else evidence_id],
            }],
        }
        return httpx.Response(200, json={"choices": [{
            "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(content)},
        }]})

    deployment = replace(
        _deployment(), provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
        location=ExecutionLocation.LOCAL, endpoint_ref="local-http", secret_ref=None,
        external_transfer=False, transmitted_data_categories=(), data_processing_notice_ref=None,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond), trust_env=False) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=deployment, endpoint="http://127.0.0.1:11434", client=client,
        )
        configuration = _configuration(approval=None)
        configuration = replace(
            configuration, generation_runtime=runtime,
            generation_profile=replace(
                configuration.generation_profile, deployment=deployment,
                response_schema_version=2, prompt_ref="rag-answer-v2",
                evidence_budget=EvidenceBudget(8, 32, 12000),
            ),
        )
        service, _, _, audits = _service(
            configuration=configuration,
            decision=PolicyDecision(True, None, INSTALLATION_POLICY_ID, ()),
        )
        service.sparse_retriever = OneSourceRetriever()
        service.scope_resolver = ActiveScopeResolver()
        service.source_resolver = OneSourceResolver()
        service.turn_signer = ConversationTurnSigner(b"synthetic-test-signing-key-32-bytes")
        request = SearchRequest(
            query="synthetic fact", configuration_id=CONFIGURATION_ID,
            workspace_ids=[WORKSPACE_ID], experimental=True,
        )
        if outcome == "wrong_citation":
            with pytest.raises(AppError, match="citation"):
                await service.search(actor_id=ACTOR_ID, request=request)
            assert audits.audits[-1].status == "failed"
        else:
            result = await service.search(actor_id=ACTOR_ID, request=request)
            assert result.retrieved_evidence_ids
            assert result.generation.status.value == outcome
            if outcome == "answered":
                assert result.generation.citations[0].claim_text == "synthetic fact"
            else:
                assert result.generation.citations == ()
                assert result.generation.reason_codes == ("evidence_content_insufficient",)
        assert len(calls) == 1


@pytest.mark.parametrize("stage,with_history", [
    ("contextualize", True), ("generate", False), ("generate", True),
])
@pytest.mark.parametrize("metadata", [
    "exact", "none", "provider", "model", "deployment", "bool", "float", "overflow",
])
async def test_failed_provider_usage_is_audited_only_for_exact_execution(
    stage: str, with_history: bool, metadata: str,
) -> None:
    class FailingRuntime(InsufficientRuntime):
        def fail(self) -> None:
            execution = self.execution
            if metadata in {"bool", "float", "overflow"}:
                invalid = {"bool": True, "float": 1.5, "overflow": 2**31}[metadata]
                execution = replace(execution, input_tokens=invalid, output_tokens=invalid)
            if metadata == "provider":
                execution = replace(execution, provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE)
            elif metadata == "model":
                execution = replace(execution, provider_model_id="different-model")
            elif metadata == "deployment":
                execution = replace(execution, deployment_version_id=UUID(int=42))
            raise GenerationProviderError(
                "provider_timeout", retryable=False,
                execution=None if metadata == "none" else execution,
            )

        async def contextualize(self, request):
            if stage == "contextualize":
                self.fail()
            return await super().contextualize(request)

        async def generate(self, request):
            self.fail()

    runtime = FailingRuntime(None)
    approval = _approval()
    configuration = replace(
        _configuration(approval=approval), generation_runtime=runtime,
    )
    service, _, _, audits = _service(
        configuration=configuration,
        decision=PolicyDecision(
            True, None, INSTALLATION_POLICY_ID,
            tuple(item.policy_version_id for item in approval.workspace_policies),
            workspace_policy_snapshots=tuple(
                (item.workspace_id, item.policy_version_id) for item in approval.workspace_policies
            ),
        ),
    )
    service.sparse_retriever = OneSourceRetriever()
    service.scope_resolver = ActiveScopeResolver()
    service.source_resolver = OneSourceResolver()
    service.turn_signer = ConversationTurnSigner(b"synthetic-test-signing-key-32-bytes")
    with pytest.raises(AppError) as caught:
        await service.search(actor_id=ACTOR_ID, request=SearchRequest(
            query="synthetic fact", configuration_id=CONFIGURATION_ID,
            workspace_ids=[WORKSPACE_ID], experimental=True,
            history=[ConversationTurnRequest(role="user", content="synthetic history")]
            if with_history else [],
        ))
    assert caught.value.code == "provider_timeout"
    assert len(audits.audits) == audits.commits == 1
    audit = audits.audits[0]
    assert (audit.status, audit.safe_error_code) == ("failed", "provider_timeout")
    expected = (7, 3) if metadata == "exact" else (None, None)
    if with_history and stage == "generate":
        expected = ((expected[0] or 0) + 5, (expected[1] or 0) + 2)
    assert (audit.input_tokens, audit.output_tokens) == expected
    assert (audit.provider_reported_input_tokens, audit.provider_reported_output_tokens) == expected


@pytest.mark.parametrize("first,second,expected", [
    (None, None, None), (None, 0, 0), (5, None, 5),
    (2**31 - 2, 1, 2**31 - 1), (2**31 - 1, 1, None),
])
def test_combined_usage_remains_within_audit_integer_range(first, second, expected) -> None:
    from ai_workshop.labs.rag.search.pipeline import _combine_execution

    execution = InsufficientRuntime(None).execution
    combined = _combine_execution(
        replace(execution, input_tokens=first, output_tokens=first),
        replace(execution, input_tokens=second, output_tokens=second),
    )
    assert (combined.input_tokens, combined.output_tokens) == (expected, expected)


@pytest.mark.parametrize("invalid", [True, 1.5, 2**31])
@pytest.mark.parametrize("invalid_on", ["current", "prior", "both"])
@pytest.mark.parametrize("has_current", [False, True])
def test_failure_usage_normalizes_each_stage_before_combining(
    invalid, invalid_on: str, has_current: bool,
) -> None:
    from ai_workshop.labs.rag.search.pipeline import _failed_execution

    execution = InsufficientRuntime(None).execution
    prior = replace(
        execution, input_tokens=invalid if invalid_on in {"prior", "both"} else 5,
        output_tokens=2,
    )
    current = replace(
        execution, input_tokens=invalid if invalid_on in {"current", "both"} else 7,
        output_tokens=3,
    ) if has_current else None
    combined = _failed_execution(current, _deployment(), prior)
    expected_prior = None if invalid_on in {"prior", "both"} else 5
    expected_current = 7 if has_current and invalid_on == "prior" else None
    expected = (expected_prior or 0) + (expected_current or 0)
    if expected_prior is None and expected_current is None:
        expected = None
    assert combined is not None
    assert combined.input_tokens == expected
    assert combined.output_tokens == (5 if has_current else 2)
