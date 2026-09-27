from dataclasses import replace

import pytest

from ai_workshop.labs.rag.generation.domain import GeneratedClaim, StructuredGeneration
from ai_workshop.labs.rag.generation.execution import ProviderGenerationResult
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget
from ai_workshop.labs.rag.highlighting.domain import AnswerPolicy
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.labs.rag.retrieval.domain import SparseHit
from ai_workshop.labs.rag.search.pipeline import PipelineInput, RagExecutionPipeline
from ai_workshop.labs.rag.search.schemas import SearchRequest
from ai_workshop.shared.errors import AppError
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


@pytest.mark.parametrize("threshold,characters", [(0.0, 12000), (0.99, 12000), (0.0, 1)])
async def test_live_and_frozen_select_same_units_and_citations(threshold, characters):
    source = _source(1, "An explanation of the device warranty.")

    class Retriever:
        async def search_sparse(self, **kwargs):
            return (SparseHit(source.chunk, 1, 7.2),)

    class Sources:
        async def resolve(self, **kwargs):
            return (source,)

    class Runtime(InsufficientRuntime):
        calls = 0

        async def generate(self, request):
            self.calls += 1
            return ProviderGenerationResult(
                StructuredGeneration(
                    1, (GeneratedClaim("An explanation.", (request.evidence[0].evidence_id,)),)
                ),
                self.execution,
            )

    runtime = Runtime(None)
    approval = _approval()
    configuration = _configuration(approval=approval)
    configuration = replace(
        configuration,
        generation_runtime=runtime,
        embedding=ContextEmbedding(),
        answer_policy=AnswerPolicy(threshold, 1.0),
        generation_profile=replace(
            configuration.generation_profile,
            prompt_ref="rag-answer-v2",
            evidence_budget=EvidenceBudget(8, 32, characters),
        ),
    )
    service, _, _, _ = _service(
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
    service.sparse_retriever = Retriever()
    service.source_resolver = Sources()
    service.scope_resolver = ActiveScopeResolver()
    service.turn_signer = ConversationTurnSigner(b"synthetic-test-signing-key-32-bytes")
    request = SearchRequest(
        query="synthetic fact",
        configuration_id=CONFIGURATION_ID,
        workspace_ids=[WORKSPACE_ID],
        experimental=True,
    )
    live = await service.search(actor_id=ACTOR_ID, request=request)
    calls = runtime.calls
    pipeline = RagExecutionPipeline(**vars(service))
    from unittest.mock import AsyncMock

    frozen_scope = await service.scope_resolver.resolve()
    current_access = AsyncMock()
    # Historical READY snapshots must not consult the current active build resolver.
    pipeline.scope_resolver = type(
        "NewActiveBuild",
        (),
        {"resolve": AsyncMock(side_effect=AssertionError("active alias consulted"))},
    )()
    frozen = await pipeline.execute(
        PipelineInput(
            actor_id=ACTOR_ID,
            request=request,
            configuration=configuration,
            resolved_scope=frozen_scope,
            frozen_access=current_access,
            source_resolver=Sources(),
        )
    )
    assert live.generation.status == frozen.generation.status
    assert live.generation.citations == frozen.generation.citations
    assert [item.evidence.id for item in live.grounding_evidence] == [
        item.evidence.id for item in frozen.grounding_evidence
    ]
    assert runtime.calls == 2 * calls
    assert current_access.await_count >= 2
    if characters == 1:
        assert runtime.calls == 0


async def test_revoked_revision_approval_blocks_generation_in_shared_core():
    approval = _approval()
    configuration = _configuration(approval=approval)
    service, _, runtime_resolver, audits = _service(
        configuration=configuration,
        decision=PolicyDecision(True, None, INSTALLATION_POLICY_ID, ()),
    )
    request = SearchRequest(
        query="synthetic fact",
        configuration_id=CONFIGURATION_ID,
        workspace_ids=[WORKSPACE_ID],
        experimental=True,
    )
    # The saved approval references workspace revisions absent from the current decision.
    with pytest.raises(AppError):
        await RagExecutionPipeline(**vars(service)).execute(
            PipelineInput(
                actor_id=ACTOR_ID,
                request=request,
                configuration=configuration,
            )
        )
    assert not runtime_resolver.calls
    assert audits.audits[-1].status == "denied"
