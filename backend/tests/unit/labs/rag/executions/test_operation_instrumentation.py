from typing import cast
from uuid import uuid4

import pytest
from elasticsearch import AsyncElasticsearch

from ai_workshop.labs.rag.embeddings.contracts import EmbeddingRuntimeUnavailableError
from ai_workshop.labs.rag.embeddings.request_cache import RequestScopedEmbedding
from ai_workshop.labs.rag.embeddings.sentence_transformers import SentenceTransformerEmbedding
from ai_workshop.labs.rag.executions.observer import observed_call
from ai_workshop.labs.rag.retrieval.domain import ResolvedSearchScope, SearchBackendUnavailableError
from ai_workshop.labs.rag.retrieval.elasticsearch import (
    ElasticsearchSparseRetriever,
    PointInTimeCleanupError,
)
from ai_workshop.labs.rag.retrieval.service import HybridRetrievalService
from ai_workshop.labs.rag.search.pipeline import PipelineInput
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.embeddings.test_sentence_transformer_adapter import (
    RecordingLoader,
    RecordingModel,
    config,
)
from tests.unit.labs.rag.executions.test_operation_timings import observer
from tests.unit.labs.rag.retrieval.test_frozen_pit import ACTOR_ID, PitClient, _scope, _target
from tests.unit.labs.rag.retrieval.test_service import (
    INDEXING_PROFILE_ID,
    BlockingDenseRetriever,
    FailingAfterDenseStartsSparseRetriever,
    RecordingDenseRetriever,
    RecordingEmbedding,
    RecordingScopeResolver,
    RecordingSparseRetriever,
    _active_alias,
    _bm25_profile,
    _hybrid_profile,
)
from tests.unit.labs.rag.search.test_request_embedding_lifetime import harness


def stage_operations(item, stage):
    row = next(
        row for row in reversed(item.recorder.rows)
        if row["stage"] == stage and row["state"] != "running"
    )
    return {entry["name"]: entry for entry in row["operations"]}


async def in_stage(item, stage, work):
    await item.begin(stage)
    try:
        return await work()
    finally:
        await item.end(stage)


async def test_embedding_records_real_load_tokenization_and_request_reuse(tmp_path):
    item = observer()
    loader = RecordingLoader(RecordingModel())
    adapter = SentenceTransformerEmbedding(config(), cache_folder=tmp_path, loader=loader)
    cached = RequestScopedEmbedding(adapter)

    async def work():
        assert cached.count_query_tokens("private query") == 5
        assert cached.count_tokens("private document") == 5
        assert cached.encode_query("private query") == [1.0, 0.0, 0.0]
        cached.encode_query("private query")
        assert len(cached.encode_documents(["first", "first", "second"])) == 3
        assert len(cached.encode_documents(["second", "first"])) == 2

    await observed_call(in_stage(item, "selection", work), item)
    operations = stage_operations(item, "selection")
    assert set(operations) == {
        "embedding.model_load", "embedding.tokenize", "embedding.query", "embedding.documents",
    }
    assert operations["embedding.model_load"]["calls"] == 1
    assert operations["embedding.tokenize"]["items"] == 2
    assert operations["embedding.query"]["items"] == 2
    assert operations["embedding.query"]["reused_items"] == 1
    assert operations["embedding.documents"]["items"] == 5
    assert operations["embedding.documents"]["reused_items"] == 3
    assert "private" not in str(item.recorder.rows)


async def test_embedding_runtime_failure_records_failure_without_caching_it(tmp_path):
    item = observer()
    model = RecordingModel(failure=RuntimeError("private runtime failure"))
    cached = RequestScopedEmbedding(SentenceTransformerEmbedding(
        config(), cache_folder=tmp_path, loader=RecordingLoader(model),
    ))

    async def work():
        with pytest.raises(EmbeddingRuntimeUnavailableError):
            cached.encode_query("private query")
        model.failure = None
        assert cached.encode_query("private query") == [1.0, 0.0, 0.0]

    await observed_call(in_stage(item, "retrieval", work), item)
    operation = stage_operations(item, "retrieval")["embedding.query"]
    assert (operation["calls"], operation["failures"], operation["reused_items"]) == (2, 1, 0)


@pytest.mark.parametrize("hybrid", [False, True])
async def test_retrieval_records_actual_authorization_and_concurrent_branch_calls(hybrid):
    item = observer()
    events = []
    scope = ResolvedSearchScope((uuid4(),), ())
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RequestScopedEmbedding(RecordingEmbedding(events)),
        sparse_retriever=RecordingSparseRetriever(events, ()),
        dense_retriever=RecordingDenseRetriever(events, ()),
    )

    async def work():
        return await service.search(
            actor_id=uuid4(), query="query", workspace_ids=scope.workspace_ids, folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_hybrid_profile() if hybrid else _bm25_profile(),
            index_alias=_active_alias(), result_limit=3,
        )

    assert await observed_call(in_stage(item, "retrieval", work), item) == ()
    operations = stage_operations(item, "retrieval")
    assert operations["retrieval.authorize"]["calls"] == (2 if hybrid else 1)
    assert operations["retrieval.bm25"]["calls"] == 1
    assert ("retrieval.dense" in operations) is hybrid
    if hybrid:
        assert operations["retrieval.dense"]["calls"] == 1
    assert events[:1] == ["scope"]


async def test_parallel_search_failure_and_sibling_cancellation_are_both_counted():
    item = observer()
    scope = ResolvedSearchScope((uuid4(),), ())
    dense = BlockingDenseRetriever()
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver([], scope),
        embedding=RequestScopedEmbedding(RecordingEmbedding([])),
        sparse_retriever=FailingAfterDenseStartsSparseRetriever(
            dense.started, SearchBackendUnavailableError("private backend body"),
        ),
        dense_retriever=dense,
    )

    async def work():
        await service.search(
            actor_id=uuid4(), query="query", workspace_ids=scope.workspace_ids, folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID, retrieval_profile=_hybrid_profile(),
            index_alias=_active_alias(), result_limit=3,
        )

    with pytest.raises(AppError) as caught:
        await observed_call(in_stage(item, "retrieval", work), item)
    assert caught.value.code == "hybrid_search_unavailable"
    operations = stage_operations(item, "retrieval")
    assert operations["retrieval.bm25"]["failures"] == 1
    assert operations["retrieval.dense"]["failures"] == 1
    assert dense.cancelled


@pytest.mark.parametrize("cleanup_failure", [False, True])
async def test_frozen_retrieval_records_descriptions_and_pit_cleanup(cleanup_failure):
    item = observer()
    client = PitClient()
    if cleanup_failure:
        client.close_failure = RuntimeError("private PIT failure")

    async def work():
        return await ElasticsearchSparseRetriever(cast(AsyncElasticsearch, client)).search_sparse(
            index_alias=_target(), query="frozen", actor_id=ACTOR_ID, scope=_scope(), top_k=2,
        )

    if cleanup_failure:
        with pytest.raises(PointInTimeCleanupError):
            await observed_call(in_stage(item, "retrieval", work), item)
    else:
        result = await observed_call(in_stage(item, "retrieval", work), item)
        assert result[0].chunk.text == "frozen evidence"
    operations = stage_operations(item, "retrieval")
    assert operations["retrieval.describe"]["calls"] == 2
    assert operations["retrieval.pit_open"]["calls"] == 1
    assert operations["retrieval.pit_close"]["calls"] == 1
    assert operations["retrieval.pit_close"]["failures"] == int(cleanup_failure)


async def test_pipeline_records_sources_and_both_selectors_with_shared_keyword_cache(tmp_path):
    item = observer()
    service, request, configuration, _, _ = harness(tmp_path)
    result = await service.execute(
        PipelineInput(actor_id=ACTOR_ID, request=request, configuration=configuration),
        observer=item,
    )
    assert result.selection.answer.excerpt == "synthetic fact"
    assert result.generation.text == "synthetic fact"
    retrieval = stage_operations(item, "retrieval")
    selection = stage_operations(item, "selection")
    assert retrieval["retrieval.sources"]["items"] == 1
    assert selection["selection.extractive"]["calls"] == 1
    assert selection["selection.context"]["calls"] == 1
    assert selection["keyword.normalize"]["reused_items"] >= 1
    # Exact extractive matches do not require embeddings; context embeds once.
    assert selection["embedding.query"]["calls"] == 1
    assert selection["embedding.query"]["reused_items"] == 0
    assert "synthetic fact" not in str(item.recorder.rows)
