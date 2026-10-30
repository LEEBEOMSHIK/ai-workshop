"""Claim-local calculation reuse must preserve frozen authority and resource ownership."""

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
from dataclasses import replace
from types import MappingProxyType, SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.evaluation import generative_workflow as workflow_module
from ai_workshop.labs.rag.evaluation.domain import PermissionScenario
from ai_workshop.labs.rag.evaluation.embedding_reuse import FrozenEmbeddingResults
from ai_workshop.labs.rag.evaluation.generative_adapter import FrozenGenerativeAdapter
from ai_workshop.labs.rag.generation.domain import GenerationOutcome, GenerationStatus
from ai_workshop.labs.rag.generation.execution import track_local_http_attempt
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.retrieval.domain import FrozenIndexIdentity, FrozenIndexTarget
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.executions.test_observer import Recorder
from tests.unit.labs.rag.highlighting.test_evidence_selector import _source
from tests.unit.labs.rag.search.test_generation_policy_gate import (
    ACTOR_ID,
    WORKSPACE_ID,
    StubEmbedding,
    _configuration,
)
from tests.unit.labs.rag.search.test_request_embedding_lifetime import harness


def adapter_harness(*, results=None, owned=True, configuration=None):
    configuration = configuration or _configuration(approval=None)
    embedding = StubEmbedding()
    factory = Mock(return_value=Mock(dimension=embedding.dimension)) if owned else None
    frozen = replace(
        configuration, embedding=embedding, request_owned_embedding_factory=factory,
    )
    source = _source(1, "synthetic fact")
    chunk = source.chunk
    descriptor = IndexDescriptor(2, "cosine")
    target = FrozenIndexTarget(
        descriptor=descriptor, index_prefix="synthetic",
        indexing_profile_id=configuration.indexing_profile_id,
        identities=(FrozenIndexIdentity(
            descriptor.concrete_index_name(
                "synthetic", configuration.indexing_profile_id, chunk.index_build_id,
            ),
            "synthetic-index-uuid", chunk.index_build_id, chunk.projection_id,
            configuration.indexing_profile_id, 2, descriptor.mapping_version,
        ),),
        asset_version_ids=(chunk.asset_version_id,),
    )
    candidate = SimpleNamespace(
        id=UUID(int=11), configuration_id=configuration.configuration_id,
        configuration_version_id=configuration.configuration_version_id, retrieval_k=3,
        component_snapshot={
            "profiles": [{"id": str(configuration.generation_profile.profile_id),
                          "version": configuration.generation_profile.profile_version}],
            "models": [{"config": {"revision": "a" * 40, "prefix": "query: "}}],
        },
        execution_snapshot={"sources": [{
            "chunk_id": str(chunk.chunk_id), "document_id": str(source.document_id),
            "asset_version_id": str(chunk.asset_version_id),
            "projection_id": str(chunk.projection_id), "index_build_id": str(chunk.index_build_id),
            "indexing_profile_id": str(configuration.indexing_profile_id),
            "asset_version_number": source.asset_version_number, "media_type": source.media_type,
            "workspace": {"id": str(WORKSPACE_ID)}, "title": chunk.title,
            "section_path": list(chunk.section_path), "chunk_text": chunk.text,
            "evidence_units": [{
                "id": str(unit.id), "ordinal": unit.ordinal, "text": unit.text,
                "element_id": str(unit.location.element_id), "page": unit.location.page,
                "char_start": unit.location.char_start, "char_end": unit.location.char_end,
                "bbox": unit.location.bbox,
            } for unit in chunk.evidence_units],
        }]},
    )
    scenario = PermissionScenario(
        "synthetic", "owner", (WORKSPACE_ID,), (), frozenset({UUID(int=21), UUID(int=22)}),
        frozenset({UUID(int=23)}), "2026-10-26T00:00:00Z",
    )
    case = SimpleNamespace(id=UUID(int=12), query="synthetic fact", permission_scenario=scenario)
    access = SimpleNamespace(validate=AsyncMock())
    resolver = SimpleNamespace(resolve_version=AsyncMock(return_value=configuration))
    adapter = FrozenGenerativeAdapter(
        SimpleNamespace(
            prepare_target=AsyncMock(return_value=target),
            _resolve_configuration=lambda *_: frozen,
            _resolve_scope=lambda *_: scenario,
        ),
        resolver, access, **({"embedding_results": results} if results is not None else {}),
    )
    return adapter, candidate, case, frozen, factory, access, resolver


def test_explicit_result_store_dependency_does_not_construct_a_runtime():
    results = SimpleNamespace(bound=Mock())
    _, _, _, _, factory, _, _ = adapter_harness(results=results)
    factory.assert_not_called()
    results.bound.assert_not_called()


async def test_enabled_adapter_binds_only_frozen_owned_factory_lazily():
    results = SimpleNamespace(bound=Mock(return_value=object()))
    adapter, candidate, case, frozen, factory, access, resolver = adapter_harness(results=results)
    prepared = await adapter.prepare(ACTOR_ID, candidate, case)
    assert prepared.configuration.embedding is frozen.embedding
    assert prepared.configuration.request_owned_embedding_factory is not factory
    factory.assert_not_called()
    results.bound.assert_not_called()
    lease = prepared.configuration.request_owned_embedding_factory()
    assert lease is results.bound.return_value
    bound = results.bound.call_args.kwargs
    assert bound["factory"] is factory
    assert bound["dimension"] == frozen.embedding.dimension
    assert len(bound["namespace"]) == 64
    assert set(bound["namespace"]) <= set("0123456789abcdef")
    await prepared.frozen_access(prepared.resolved_scope.authorized_documents)
    await prepared.frozen_access(prepared.resolved_scope.authorized_documents)
    assert access.validate.await_count == 2
    resolver.resolve_version.assert_awaited_once_with(candidate.configuration_version_id, ACTOR_ID)


@pytest.mark.parametrize("enabled,owned", [(False, True), (False, False), (True, False)])
async def test_disabled_and_borrowed_frozen_paths_keep_original_factory(enabled, owned):
    results = SimpleNamespace(bound=Mock())
    adapter, candidate, case, frozen, factory, _, _ = adapter_harness(
        results=results if enabled else None, owned=owned,
    )
    prepared = await adapter.prepare(ACTOR_ID, candidate, case)
    assert prepared.configuration.embedding is frozen.embedding
    assert prepared.configuration.request_owned_embedding_factory is factory
    results.bound.assert_not_called()


async def namespace_for(adapter, candidate, case, results, actor=ACTOR_ID):
    prepared = await adapter.prepare(actor, candidate, case)
    prepared.configuration.request_owned_embedding_factory()
    return results.bound.call_args.kwargs["namespace"]


@pytest.mark.parametrize("changed", [
    "actor", "candidate", "case", "model", "source", "scenario_name", "scenario_actor",
    "workspace", "folder", "authorized", "forbidden", "as_of",
])
async def test_namespace_separates_every_frozen_identity_and_permission_field(changed):
    results = SimpleNamespace(bound=Mock())
    adapter, candidate, case, _, _, _, _ = adapter_harness(results=results)
    first = await namespace_for(adapter, candidate, case, results)
    actor = ACTOR_ID
    if changed == "actor":
        actor = uuid4()
    elif changed == "candidate":
        candidate.id = uuid4()
    elif changed == "case":
        case.id = uuid4()
    elif changed == "model":
        candidate.component_snapshot["models"][0]["config"]["revision"] = "b" * 40
    elif changed == "source":
        candidate.execution_snapshot["sources"][0]["chunk_text"] += " changed"
    else:
        field, value = {
            "scenario_name": ("name", "different"),
            "scenario_actor": ("actor", "reviewer"),
            "workspace": ("workspace_ids", (WORKSPACE_ID, uuid4())),
            "folder": ("folder_ids", (uuid4(),)),
            "authorized": ("authorized_source_ids", frozenset({uuid4()})),
            "forbidden": ("forbidden_source_ids", frozenset({uuid4()})),
            "as_of": ("as_of", "2026-10-27T00:00:00Z"),
        }[changed]
        case.permission_scenario = replace(case.permission_scenario, **{field: value})
    assert await namespace_for(adapter, candidate, case, results, actor) != first


async def test_namespace_is_canonical_for_mapping_order_and_permission_sets():
    results = SimpleNamespace(bound=Mock())
    adapter, candidate, case, _, _, _, _ = adapter_harness(results=results)
    first = await namespace_for(adapter, candidate, case, results)
    candidate.component_snapshot = MappingProxyType(dict(
        reversed(list(deepcopy(candidate.component_snapshot).items())),
    ))
    candidate.execution_snapshot = MappingProxyType(candidate.execution_snapshot)
    case.permission_scenario = replace(
        case.permission_scenario, authorized_source_ids=frozenset([UUID(int=22), UUID(int=21)]),
    )
    assert await namespace_for(adapter, candidate, case, results) == first


@pytest.mark.parametrize("field", ["configuration_id", "configuration_version_id"])
async def test_namespace_separates_candidate_configuration_and_version(field):
    results = SimpleNamespace(bound=Mock())
    original = _configuration(approval=None)
    adapter, candidate, case, _, _, _, _ = adapter_harness(results=results, configuration=original)
    first = await namespace_for(adapter, candidate, case, results)
    adapter, candidate, case, _, _, _, _ = adapter_harness(
        results=results, configuration=replace(original, **{field: uuid4()}),
    )
    assert await namespace_for(adapter, candidate, case, results) != first


@pytest.mark.parametrize("history", [False, True])
async def test_repeat_uses_exact_results_without_loading_model_and_rechecks_access(
    tmp_path, history,
):
    service, request, configuration, factory, runtime = harness(tmp_path, history=history)
    results = FrozenEmbeddingResults(max_bytes=1024 * 1024)
    adapter, candidate, case, _, _, access, resolver = adapter_harness(
        results=results, configuration=configuration,
    )
    adapter.frozen._resolve_configuration = lambda *_: configuration
    candidate.execution_snapshot["case_histories"] = {
        str(case.id): [item.model_dump(mode="json") for item in request.history],
    }
    sparse = AsyncMock(wraps=service.sparse_retriever.search_sparse)
    service.sparse_retriever.search_sparse = sparse
    try:
        first = await service.execute(await adapter.prepare(ACTOR_ID, candidate, case))
        first_validations = access.validate.await_count
        assert first_validations > 1
        second = await service.execute(await adapter.prepare(ACTOR_ID, candidate, case))
        assert access.validate.await_count == first_validations * 2
        assert resolver.resolve_version.await_count == 2
        assert sparse.await_count == 2
        assert first.grounding_evidence == second.grounding_evidence
        assert first.retrieved_evidence_ids == second.retrieved_evidence_ids
        assert first.selection == second.selection
        assert first.generation.text == second.generation.text == "synthetic fact"
        assert first.generation.citations == second.generation.citations
        assert len(runtime.requests) == 2
        assert runtime.requests[0].evidence == runtime.requests[1].evidence
        assert runtime.requests[0].history == runtime.requests[1].history
        assert len(factory.models) == len(factory.adapters) == 1
        assert factory.models[0]() is None
        assert factory.adapters[0]._closed
        assert configuration.embedding._model is None and not configuration.embedding._closed
    finally:
        results.close()


async def test_warm_results_do_not_bypass_revoked_access(tmp_path):
    service, _, configuration, factory, runtime = harness(tmp_path)
    results = FrozenEmbeddingResults(max_bytes=1024 * 1024)
    adapter, candidate, case, _, _, access, _ = adapter_harness(
        results=results, configuration=configuration,
    )
    adapter.frozen._resolve_configuration = lambda *_: configuration
    try:
        await service.execute(await adapter.prepare(ACTOR_ID, candidate, case))
        access.validate.side_effect = AppError("not_found", "Synthetic denial.", 404)
        with pytest.raises(AppError) as denied:
            await service.execute(await adapter.prepare(ACTOR_ID, candidate, case))
        assert denied.value.code == "not_found"
        assert len(runtime.requests) == 1
        assert len(factory.models) == 1 and factory.models[0]() is None
    finally:
        results.close()


@pytest.mark.parametrize("max_bytes", [0, 4096])
async def test_claim_records_effective_reuse_configuration(monkeypatch, max_bytes):
    monkeypatch.setattr(workflow_module, "capture_worker_runtime", lambda **_: {"existing": "kept"})
    workflow = workflow_module.GenerativeWorkflow(None, SimpleNamespace(
        environment="test", frozen_evaluation_embedding_cache_bytes=max_bytes,
    ))
    workflow.repository.claim_run = AsyncMock(return_value=None)
    await workflow.run(uuid4())
    recorded = workflow.repository.claim_run.call_args.args[1]
    assert recorded["existing"] == "kept"
    assert recorded.get("embedding_result_reuse") == {
        "version": 1, "scope": "claim", "max_bytes": max_bytes, "enabled": bool(max_bytes),
    }


@pytest.mark.parametrize("failure", [None, RuntimeError("synthetic"), asyncio.CancelledError()])
async def test_claim_owns_one_result_store_and_clears_it_even_on_failure(monkeypatch, failure):
    stores = []

    class Results:
        def __init__(self, max_bytes):
            assert max_bytes == 4096
            self.closed = False
            stores.append(self)

        def close(self):
            self.closed = True

    monkeypatch.setattr(workflow_module, "FrozenEmbeddingResults", Results, raising=False)
    workflow = workflow_module.GenerativeWorkflow(None, SimpleNamespace(
        frozen_evaluation_embedding_cache_bytes=4096,
    ))
    received = []

    async def attempts(run_id, token, *, embedding_results=None):
        received.append(embedding_results)
        assert not embedding_results.closed
        if failure is not None:
            raise failure

    monkeypatch.setattr(workflow, "_execute_attempts", attempts, raising=False)
    for _ in range(2):
        if failure is None:
            await workflow._execute_claimed(uuid4(), uuid4())
        else:
            with pytest.raises(type(failure)) as caught:
                await workflow._execute_claimed(uuid4(), uuid4())
            assert caught.value is failure
    assert received == stores and len(stores) == 2
    assert stores[0] is not stores[1]
    assert all(store.closed for store in stores)


async def test_disabled_claim_passes_no_new_keyword_and_constructs_no_store(monkeypatch):
    factory = Mock(side_effect=AssertionError("Disabled cache must not be constructed"))
    monkeypatch.setattr(workflow_module, "FrozenEmbeddingResults", factory, raising=False)
    workflow = workflow_module.GenerativeWorkflow(None, SimpleNamespace(
        frozen_evaluation_embedding_cache_bytes=0,
    ))
    calls = []

    async def attempts(run_id, token):
        calls.append((run_id, token))

    monkeypatch.setattr(workflow, "_execute_attempts", attempts, raising=False)
    run_id, token = uuid4(), uuid4()
    await workflow._execute_claimed(run_id, token)
    assert calls == [(run_id, token)]
    factory.assert_not_called()


@pytest.mark.parametrize("max_bytes", [0, 4096])
@pytest.mark.parametrize("failure", [None, "prepare", "cancel", "persistence", "unconfirmed"])
async def test_attempt_loop_injects_only_enabled_store_and_preserves_terminal_cleanup(
    monkeypatch, max_bytes, failure,
):
    run_id, token, case_id = uuid4(), uuid4(), uuid4()
    run = SimpleNamespace(owner_id=uuid4(), dataset_snapshot_id=uuid4(), input_approval=None)
    attempts = [SimpleNamespace(
        id=uuid4(), execution_id=uuid4(), case_id=case_id, configuration_version_id=uuid4(),
    ) for _ in range(2)]
    case = SimpleNamespace(
        id=case_id, permission_scenario=SimpleNamespace(authorized_source_ids=frozenset()),
    )
    stores, adapter_arguments, closed_frozen, completed = [], [], [], []

    class Results:
        def __init__(self, *, max_bytes):
            self.max_bytes, self.closed = max_bytes, False
            stores.append(self)

        def close(self):
            self.closed = True

    class Session:
        async def get(self, model, id):
            return run if id == run_id else SimpleNamespace(fixture_bytes=b"synthetic")

        async def scalars(self, query):
            return SimpleNamespace(all=lambda: [item.id for item in attempts])

    @asynccontextmanager
    async def sessions():
        yield Session()

    @asynccontextmanager
    async def codex(settings):
        yield None

    class Frozen:
        def __init__(self, settings):
            pass

        async def close(self):
            closed_frozen.append(self)

    class Adapter:
        def __init__(self, frozen, resolver, access, *, input_approval, **kwargs):
            adapter_arguments.append(kwargs)
            if max_bytes:
                assert kwargs == {"embedding_results": stores[0]}
                assert not stores[0].closed
            else:
                assert kwargs == {}

        async def prepare(self, *args):
            if failure == "prepare":
                raise AppError("configuration_not_ready", "Synthetic prepare failure.", 409)
            return SimpleNamespace(configuration=SimpleNamespace(generation_profile=None))

    class Pipeline:
        async def execute(self, prepared, *, observer):
            if failure == "cancel":
                raise asyncio.CancelledError
            if failure == "unconfirmed":
                async def failed_transport():
                    raise AppError("provider_timeout", "Synthetic transport failure.", 504)

                await track_local_http_attempt(failed_transport())
            return SimpleNamespace(
                retrieved_evidence_ids=(), grounding_evidence=(),
                generation=GenerationOutcome(status=GenerationStatus.INSUFFICIENT_EVIDENCE),
            )

    async def search_service(*args):
        yield Pipeline()

    class Repository:
        async def claim_attempt(self, id, claim):
            return next(item for item in attempts if item.id == id)

        async def complete_attempt(self, id, claim, result, *, error_code):
            if failure == "persistence":
                raise RuntimeError("Synthetic persistence failure")
            completed.append((id, error_code))

        async def finish_run(self, id, claim):
            assert len(completed) == 2

    monkeypatch.setattr(workflow_module, "FrozenEmbeddingResults", Results)
    monkeypatch.setattr(workflow_module, "ProductionEvaluationSearch", Frozen)
    monkeypatch.setattr(workflow_module, "FrozenGenerativeAdapter", Adapter)
    monkeypatch.setattr(workflow_module, "codex_services", codex)
    monkeypatch.setattr(workflow_module, "get_search_configuration_resolver", lambda *args: None)
    monkeypatch.setattr(workflow_module, "get_search_service", search_service)
    monkeypatch.setattr(
        workflow_module, "LocalModelHost", lambda: SimpleNamespace(aclose=AsyncMock()),
    )
    monkeypatch.setattr(workflow_module, "SqlAlchemyExecutionRecorder", lambda _: Recorder())
    monkeypatch.setattr(workflow_module, "candidate_input", lambda *args: None)
    monkeypatch.setattr(
        workflow_module, "load_evaluation_dataset", lambda _: SimpleNamespace(cases=[case]),
    )
    monkeypatch.setattr(
        workflow_module.SearchResponse, "from_domain",
        lambda _: SimpleNamespace(grounding_evidence=[]),
    )
    workflow = workflow_module.GenerativeWorkflow(sessions, SimpleNamespace(
        frozen_evaluation_embedding_cache_bytes=max_bytes,
    ))
    workflow.repository = Repository()
    if failure in {"cancel", "persistence"}:
        expected = asyncio.CancelledError if failure == "cancel" else RuntimeError
        with pytest.raises(expected):
            await workflow._execute_claimed(run_id, token)
    else:
        await workflow._execute_claimed(run_id, token)
    assert len(stores) == bool(max_bytes)
    assert all(store.closed for store in stores)
    expected_attempts = 1 if failure in {"cancel", "persistence", "unconfirmed"} else 2
    assert len(adapter_arguments) == len(closed_frozen) == expected_attempts
    if failure == "unconfirmed":
        assert completed == [(attempts[0].id, "provider_termination_unconfirmed")]
