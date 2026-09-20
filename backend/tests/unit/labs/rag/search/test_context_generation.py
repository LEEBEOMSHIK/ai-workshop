from dataclasses import replace

import pytest

from ai_workshop.labs.rag.generation.domain import GeneratedClaim, StructuredGeneration
from ai_workshop.labs.rag.generation.execution import ProviderGenerationResult
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget
from ai_workshop.labs.rag.highlighting.domain import AnswerPolicy, AnswerStatus
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.labs.rag.retrieval.domain import SparseHit
from ai_workshop.labs.rag.search.schemas import SearchRequest, SearchResponse
from tests.unit.labs.rag.highlighting.test_context import ContextEmbedding
from tests.unit.labs.rag.highlighting.test_evidence_selector import _source
from tests.unit.labs.rag.search.test_generation_policy_gate import (
    ACTOR_ID,
    CONFIGURATION_ID,
    INSTALLATION_POLICY_ID,
    WORKSPACE_ID,
    _approval,
    _configuration,
    _service,
)
from tests.unit.labs.rag.search.test_provider_insufficient_evidence import (
    ActiveScopeResolver,
    InsufficientRuntime,
)


@pytest.mark.parametrize("diagnostics", [False, True])
async def test_context_only_evidence_reaches_generation_and_every_citation_is_returned(diagnostics):
    source = _source(1, "An explanation of the device warranty.")

    class Retriever:
        async def search_sparse(self, **kwargs):
            return (SparseHit(source.chunk, 1, 7.2),)

    class Sources:
        async def resolve(self, **kwargs):
            return (source,)

    class Runtime(InsufficientRuntime):
        received = None

        async def generate(self, request):
            self.received = request
            return ProviderGenerationResult(
                StructuredGeneration(1, (GeneratedClaim("An explanation.",
                    (request.evidence[0].evidence_id,)),)), self.execution,
            )

    runtime = Runtime(None)
    approval = _approval()
    configuration = _configuration(approval=approval)
    configuration = replace(configuration, generation_runtime=runtime,
        embedding=ContextEmbedding(), answer_policy=AnswerPolicy(0.9, 1.0),
        generation_profile=replace(configuration.generation_profile,
            prompt_ref="rag-answer-v2", evidence_budget=EvidenceBudget(8, 32, 12000)))
    service, _, _, audits = _service(configuration=configuration, decision=PolicyDecision(
        True, None, INSTALLATION_POLICY_ID,
        tuple(item.policy_version_id for item in approval.workspace_policies),
        workspace_policy_snapshots=tuple((item.workspace_id, item.policy_version_id)
                                        for item in approval.workspace_policies),
    ))
    service.sparse_retriever = Retriever()
    service.source_resolver = Sources()
    service.scope_resolver = ActiveScopeResolver()
    service.turn_signer = ConversationTurnSigner(b"synthetic-test-signing-key-32-bytes")
    result = await service.search(actor_id=ACTOR_ID, request=SearchRequest(
        query="synthetic fact", configuration_id=CONFIGURATION_ID,
        workspace_ids=[WORKSPACE_ID], experimental=True, include_diagnostics=diagnostics))
    assert result.selection.status is AnswerStatus.INSUFFICIENT_EVIDENCE
    assert runtime.received is not None
    assert result.generation.status.value == "answered"
    assert [item.evidence.id for item in result.grounding_evidence] == [
        item.evidence_id for item in runtime.received.evidence]
    assert audits.audits[-1].evidence_ids == (source.chunk.evidence_units[0].id,)
    response = SearchResponse.from_domain(result)
    assert bool(response.diagnostics) is diagnostics
    if response.diagnostics:
        assert response.diagnostics.candidates[0].sparse_score == 7.2
        assert response.diagnostics.candidates[0].dense_score is None
        assert response.diagnostics.stages_ms["contextualization"] is None
        assert response.diagnostics.stages_ms["generation"] is not None
