"""Offline pipeline regression: the selected table bundle is the transmitted one."""

from dataclasses import replace

import pytest

from ai_workshop.labs.rag.generation.domain import GeneratedClaim, StructuredGeneration
from ai_workshop.labs.rag.generation.execution import ProviderGenerationResult
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget
from ai_workshop.labs.rag.highlighting.domain import AnswerPolicy
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.labs.rag.retrieval.domain import (
    ResolvedSearchScope,
    SelectedDocumentIdentity,
    SparseHit,
)
from ai_workshop.labs.rag.search.schemas import SearchRequest, SearchResponse
from tests.unit.labs.rag.highlighting.test_stored_table_context import STORED_QUERY, stored_source
from tests.unit.labs.rag.highlighting.test_table_context import (
    QUERY,
    LowScores,
    expected_units,
    table_source,
)
from tests.unit.labs.rag.search.test_generation_policy_gate import (
    ACTOR_ID,
    CONFIGURATION_ID,
    INSTALLATION_POLICY_ID,
    _approval,
    _configuration,
    _service,
)
from tests.unit.labs.rag.search.test_provider_insufficient_evidence import InsufficientRuntime


@pytest.mark.parametrize("diagnostics", [False, True])
@pytest.mark.parametrize("stored", [False, True])
async def test_projected_units_reach_generation_audit_and_source_citations(diagnostics, stored):
    source = stored_source() if stored else table_source()
    query = STORED_QUERY if stored else QUERY
    workspace_id = source.chunk.workspace_id
    expected = expected_units(source)
    cited = source.chunk.evidence_units[19]

    class Retriever:
        async def search_sparse(self, **kwargs):
            return (SparseHit(source.chunk, 1, 7.2),)

    class Sources:
        async def resolve(self, **kwargs):
            return (source,)

    class Scope:
        async def resolve(self, **kwargs):
            chunk = source.chunk
            return ResolvedSearchScope(
                (workspace_id,), (), asset_version_ids=(chunk.asset_version_id,),
                index_build_ids=(chunk.index_build_id,),
                authorized_documents=(SelectedDocumentIdentity(
                    source.document_id, chunk.asset_version_id,
                    chunk.projection_id, chunk.index_build_id),))

    class Runtime(InsufficientRuntime):
        received = None

        async def generate(self, request):
            self.received = request
            return ProviderGenerationResult(
                StructuredGeneration(1, (GeneratedClaim(cited.text, (cited.id,)),)),
                self.execution)

    runtime = Runtime(None)
    approval = _approval()
    approval = replace(approval, workspace_policies=(replace(
        approval.workspace_policies[0], workspace_id=workspace_id),))
    configuration = _configuration(approval=approval)
    configuration = replace(configuration, workspace_ids=(workspace_id,),
        generation_runtime=runtime, embedding=LowScores(),
        answer_policy=AnswerPolicy(0.9, 0.5), generation_profile=replace(
            configuration.generation_profile, prompt_ref="rag-answer-v2",
            evidence_budget=EvidenceBudget(8, 32, 12000)))
    service, _, _, audits = _service(configuration=configuration, decision=PolicyDecision(
        True, None, INSTALLATION_POLICY_ID,
        tuple(item.policy_version_id for item in approval.workspace_policies),
        workspace_policy_snapshots=tuple((item.workspace_id, item.policy_version_id)
                                        for item in approval.workspace_policies)))
    service.sparse_retriever = Retriever()
    service.source_resolver = Sources()
    service.scope_resolver = Scope()
    service.turn_signer = ConversationTurnSigner(b"synthetic-test-signing-key-32-bytes")
    result = await service.search(actor_id=ACTOR_ID, request=SearchRequest(
        query=query, configuration_id=CONFIGURATION_ID, workspace_ids=[workspace_id],
        experimental=True, include_diagnostics=diagnostics))
    assert runtime.received is not None
    assert tuple(e.evidence_id for e in runtime.received.evidence) == tuple(u.id for u in expected)
    assert tuple(e.text for e in runtime.received.evidence) == tuple(u.text for u in expected)
    assert tuple(e.evidence for e in result.grounding_evidence) == expected
    assert audits.audits[-1].evidence_ids == tuple(u.id for u in expected)
    response = SearchResponse.from_domain(result)
    assert response.generation.status == "answered"
    assert response.generation.citations[0].claim_text == cited.text
    assert bool(response.diagnostics) is diagnostics
