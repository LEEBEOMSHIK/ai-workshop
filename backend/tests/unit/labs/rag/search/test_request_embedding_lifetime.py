import asyncio
import weakref
from dataclasses import replace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.embeddings.contracts import EmbeddingRuntimeUnavailableError
from ai_workshop.labs.rag.embeddings.sentence_transformers import SentenceTransformerEmbedding
from ai_workshop.labs.rag.generation.domain import GeneratedClaim, StructuredGeneration
from ai_workshop.labs.rag.generation.execution import ProviderGenerationResult
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.labs.rag.search.schemas import (
    ConversationTurnRequest,
    SearchRequest,
    SearchResponse,
)
from tests.unit.labs.rag.embeddings.test_sentence_transformer_adapter import RecordingModel, config
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
    OneSourceResolver,
    OneSourceRetriever,
)


class OwnedFactory:
    def __init__(self, path):
        self.path = path
        self.adapters = []
        self.models = []

    def __call__(self):
        def load(*args, **kwargs):
            model = RecordingModel(dimension=2, output=[[1.0, 0.0]])
            self.models.append(weakref.ref(model))
            return model

        adapter = SentenceTransformerEmbedding(
            config(dimension=2), cache_folder=self.path, loader=load
        )
        self.adapters.append(adapter)
        return adapter


class AnswerRuntime(InsufficientRuntime):
    def __init__(self, check):
        super().__init__(None)
        self.check = check
        self.requests = []

    async def generate(self, request):
        self.check()
        self.requests.append(request)
        return ProviderGenerationResult(
            StructuredGeneration(
                1, (GeneratedClaim("synthetic fact", (request.evidence[0].evidence_id,)),)
            ),
            self.execution,
        )


def harness(tmp_path, *, owned=True, history=False):
    factory = OwnedFactory(tmp_path)
    borrowed = factory()
    factory.adapters.clear()

    def check():
        assert factory.models
        assert (factory.models[-1]() is None) is owned

    runtime = AnswerRuntime(check)
    approval = _approval()
    configuration = _configuration(approval=approval)
    configuration = replace(
        configuration,
        embedding=borrowed,
        generation_runtime=runtime,
        request_owned_embedding_factory=factory if owned else None,
        generation_profile=replace(
            configuration.generation_profile,
            prompt_ref="rag-answer-v2",
            evidence_budget=EvidenceBudget(8, 32, 12000),
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
    service.sparse_retriever = OneSourceRetriever()
    service.source_resolver = OneSourceResolver()
    service.scope_resolver = ActiveScopeResolver()
    service.turn_signer = ConversationTurnSigner(b"synthetic-test-signing-key-32-bytes")
    request = SearchRequest(
        query="synthetic fact",
        configuration_id=CONFIGURATION_ID,
        workspace_ids=[WORKSPACE_ID],
        experimental=True,
        include_diagnostics=True,
        history=[ConversationTurnRequest(role="user", content="earlier synthetic question")]
        if history
        else [],
    )
    return service, request, configuration, factory, runtime


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("history", [False, True])
async def test_model_released_before_answer_preserves_search_evidence_and_citations(
    tmp_path, owned, history
):
    service, request, configuration, factory, runtime = harness(
        tmp_path, owned=owned, history=history
    )
    result = await service.search(actor_id=ACTOR_ID, request=request)
    assert result.configuration is configuration
    assert result.selection.answer.excerpt == "synthetic fact"
    evidence_id = UUID("50000000-0000-0000-0000-000000000001")
    assert result.retrieved_evidence_ids == (evidence_id,)
    assert result.generation.status.value == "answered"
    assert result.generation.text == "synthetic fact"
    assert result.generation.citations[0].evidence_ids == (evidence_id,)
    assert tuple(e.evidence.id for e in result.grounding_evidence) == (evidence_id,)
    assert len(runtime.requests) == 1
    assert runtime.requests[0].evidence[0].text == "synthetic fact"
    assert bool(runtime.requests[0].history) is history
    assert result.diagnostics.candidates[0].selected
    if owned:
        with pytest.raises(EmbeddingRuntimeUnavailableError, match="closed"):
            factory.adapters[0].encode_query("synthetic fact")
        # The original lazy/borrowed adapter remains usable; it was never closed.
        assert configuration.embedding.encode_query("synthetic fact") == [1.0, 0.0]


@pytest.mark.parametrize("owned", [False, True])
@pytest.mark.parametrize("phase", ["health", "sources"])
@pytest.mark.parametrize("cancel", [False, True])
async def test_failed_or_cancelled_request_releases_only_owned_model(
    tmp_path, phase, cancel, owned
):
    service, request, _, factory, runtime = harness(tmp_path, history=True, owned=owned)
    entered = asyncio.Event()
    never = asyncio.Event()
    failure = RuntimeError("synthetic dependency failure")

    async def fail(*args, **kwargs):
        assert factory.models[0]() is not None
        entered.set()
        if cancel:
            await never.wait()
        raise failure

    if phase == "health":
        runtime.health = fail
    else:
        service.source_resolver.resolve = fail
    task = asyncio.create_task(service.search(actor_id=ACTOR_ID, request=request))
    if cancel:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError) as raised:
        await task
    if not cancel:
        assert raised.value is failure
    assert (factory.models[0]() is None) is owned
    assert runtime.requests == []


async def test_concurrent_reuse_of_configuration_keeps_other_request_model_alive(tmp_path):
    service, request, configuration, factory, runtime = harness(tmp_path)
    entered = asyncio.Event()
    resume = asyncio.Event()
    original = service.source_resolver.resolve
    calls = 0

    async def sources(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            entered.set()
            await resume.wait()
        return await original(**kwargs)

    service.source_resolver.resolve = sources
    first = asyncio.create_task(service.search(actor_id=ACTOR_ID, request=request))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert factory.models[0]() is not None
        second = await service.search(actor_id=ACTOR_ID, request=request)
        assert second.configuration is configuration
        assert factory.adapters[0] is not factory.adapters[1]
        assert factory.models[0]() is not None
        assert factory.models[1]() is None
        resume.set()
        first_result = await first
        assert first_result.generation.text == second.generation.text == "synthetic fact"
        assert first_result.generation.citations == second.generation.citations
        assert first_result.generation.turn_id != second.generation.turn_id
        assert all(model() is None for model in factory.models)
        assert len(runtime.requests) == 2
    finally:
        resume.set()
        if not first.done():
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first


async def test_returned_configuration_supports_sequential_execution(tmp_path):
    from ai_workshop.labs.rag.search.pipeline import PipelineInput

    service, request, configuration, factory, _ = harness(tmp_path)
    first = await service.search(actor_id=ACTOR_ID, request=request)
    second = await service.execute(PipelineInput(ACTOR_ID, request, first.configuration))
    assert first.configuration is second.configuration is configuration
    assert len(factory.adapters) == 2
    assert factory.adapters[0] is not factory.adapters[1]
    assert len(factory.models) == 2
    assert all(model() is None for model in factory.models)
    assert first.grounding_evidence == second.grounding_evidence


@pytest.mark.parametrize("cancel", [False, True])
async def test_generation_failure_or_cancel_keeps_model_released(tmp_path, cancel):
    service, request, _, factory, runtime = harness(tmp_path)
    entered = asyncio.Event()
    never = asyncio.Event()

    async def fail(request):
        assert factory.models[0]() is None
        entered.set()
        if cancel:
            await never.wait()
        raise RuntimeError("synthetic generation failure")

    runtime.generate = fail
    task = asyncio.create_task(service.search(actor_id=ACTOR_ID, request=request))
    if cancel:
        await asyncio.wait_for(entered.wait(), 5)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else RuntimeError):
        await task
    assert factory.models[0]() is None


async def test_early_validation_rejection_closes_without_loading(tmp_path):
    from ai_workshop.shared.errors import AppError

    service, request, _, factory, _ = harness(tmp_path)
    request = request.model_copy(update={"experimental": False})
    with pytest.raises(AppError) as raised:
        await service.search(actor_id=ACTOR_ID, request=request)
    assert raised.value.code == "experimental_opt_in_required"
    assert factory.models == []
    with pytest.raises(EmbeddingRuntimeUnavailableError, match="closed"):
        factory.adapters[0].count_tokens("synthetic")
    assert factory.models == []


async def test_hybrid_query_vector_and_fused_evidence_survive_early_release(tmp_path):
    from ai_workshop.labs.rag.retrieval.domain import DenseHit
    from tests.unit.labs.rag.highlighting.test_evidence_selector import _source

    service, request, configuration, factory, _ = harness(tmp_path)
    configuration = replace(
        configuration,
        retrieval_profile=replace(
            configuration.retrieval_profile,
            config={
                "bm25": {"top_k": 10},
                "dense": {"top_k": 10},
                "rrf": {"k": 60},
                "indexing_profile_id": str(configuration.indexing_profile_id),
            },
        ),
    )
    service.configuration_resolver.configuration = configuration
    dense_calls = []

    async def dense(**kwargs):
        assert factory.models[0]() is not None
        dense_calls.append(kwargs["query_vector"])
        return (DenseHit(_source(1, "synthetic fact").chunk, 1, 0.95),)

    service.dense_retriever.search_dense = dense
    result = await service.search(actor_id=ACTOR_ID, request=request)
    assert dense_calls == [(1.0, 0.0)]
    assert result.generation.text == "synthetic fact"
    response = SearchResponse.from_domain(result)
    assert response.diagnostics.candidates[0].dense_score == 0.95
    assert response.diagnostics.candidates[0].sparse_score == 1.0
    assert factory.models[0]() is None


@pytest.mark.parametrize("generation", [False, True])
async def test_empty_search_releases_without_invoking_answer_generation(tmp_path, generation):
    service, request, configuration, factory, runtime = harness(tmp_path)
    if not generation:
        configuration = replace(
            configuration, generation_profile=None, generation_runtime=None, external_approval=None
        )
        service.configuration_resolver.configuration = configuration

    async def empty(**kwargs):
        return ()

    service.sparse_retriever.search_sparse = empty
    service.source_resolver.resolve = empty
    result = await service.search(actor_id=ACTOR_ID, request=request)
    assert result.retrieved_evidence_ids == ()
    assert result.generation.status.value == (
        "insufficient_evidence" if generation else "not_requested"
    )
    assert runtime.requests == []
    assert factory.models[0]() is None
