from dataclasses import replace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.domain import (
    ContextualizationRequest,
    GenerationRequest,
    GenerationStatus,
)
from ai_workshop.labs.rag.generation.execution import (
    ProviderContextualizationResult,
    ProviderExecutionMetadata,
    ProviderGenerationResult,
    ProviderHealthResult,
)
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
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
