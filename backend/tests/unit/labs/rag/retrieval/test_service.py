import asyncio
from dataclasses import replace
from typing import NoReturn
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor
from ai_workshop.labs.rag.models.domain import Profile, ProfileKind
from ai_workshop.labs.rag.retrieval.domain import (
    ActiveIndexAlias,
    DenseHit,
    QueryEmbeddingUnavailableError,
    ResolvedSearchScope,
    RetrievedChunk,
    SearchBackendUnavailableError,
    SparseHit,
)
from ai_workshop.labs.rag.retrieval.service import HybridRetrievalService
from ai_workshop.shared.errors import AppError

INDEXING_PROFILE_ID = UUID("00000000-0000-0000-0000-000000000899")


def _chunk(value: int) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=UUID(f"00000000-0000-0000-0000-{value:012d}"),
        projection_id=uuid4(),
        asset_version_id=uuid4(),
        workspace_id=uuid4(),
        folder_id=None,
        index_build_id=uuid4(),
        title=f"chunk-{value}",
        section_path=("section",),
        text=f"text-{value}",
        evidence_units=(),
    )


def _hybrid_profile(indexing_profile_id: UUID | None = None) -> Profile:
    return Profile.create(
        kind=ProfileKind.RETRIEVAL,
        name="hybrid",
        version=1,
        config={
            "bm25": {"top_k": 3},
            "dense": {"top_k": 3},
            "rrf": {"k": 60},
            "indexing_profile_id": str(indexing_profile_id or INDEXING_PROFILE_ID),
        },
        bindings=(),
    )


def _bm25_profile() -> Profile:
    return Profile.create(
        kind=ProfileKind.RETRIEVAL,
        name="bm25",
        version=1,
        config={"bm25": {"top_k": 3}},
        bindings=(),
    )


def _profile_with_dense(value: object) -> Profile:
    return Profile.create(
        kind=ProfileKind.RETRIEVAL,
        name="invalid-dense",
        version=1,
        config={
            "bm25": {"top_k": 3},
            "dense": value,
            "rrf": {"k": 60},
            "indexing_profile_id": str(uuid4()),
        },
        bindings=(),
    )


def _active_alias(profile_id: UUID | None = None) -> ActiveIndexAlias:
    return ActiveIndexAlias(
        descriptor=IndexDescriptor(vector_dimension=2, similarity="cosine"),
        index_prefix="ai-workshop-rag",
        indexing_profile_id=profile_id or INDEXING_PROFILE_ID,
    )


def _exception_leaves(error: BaseException) -> tuple[BaseException, ...]:
    if isinstance(error, BaseExceptionGroup):
        return tuple(
            leaf
            for nested in error.exceptions
            for leaf in _exception_leaves(nested)
        )
    return (error,)


class RecordingScopeResolver:
    def __init__(
        self,
        events: list[str],
        scope: ResolvedSearchScope,
        *,
        allow_empty: bool = False,
    ) -> None:
        self.events = events
        self.scope = (
            scope
            if allow_empty or not scope.active_only or scope.asset_version_ids
            else replace(
                scope,
                asset_version_ids=(uuid4(),),
                index_build_ids=(uuid4(),),
            )
        )
        self.indexing_profile_ids: list[UUID | None] = []

    async def resolve(
        self,
        *,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
        indexing_profile_id: UUID | None = None,
    ) -> ResolvedSearchScope:
        del actor_id, workspace_ids, folder_ids
        self.indexing_profile_ids.append(indexing_profile_id)
        self.events.append("scope")
        return self.scope


class RecordingEmbedding:
    dimension = 2

    def __init__(
        self,
        events: list[str],
        *,
        failure: Exception | None = None,
        query_tokens: int | None = None,
    ) -> None:
        self.events = events
        self.failure = failure
        self.query_tokens = query_tokens

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def count_query_tokens(self, text: str) -> int:
        return self.query_tokens if self.query_tokens is not None else len(text.split())

    def encode_documents(self, texts: object) -> NoReturn:
        del texts
        raise AssertionError("document embedding is not part of retrieval")

    def encode_query(self, text: str) -> list[float]:
        assert text == "query"
        self.events.append("embedding")
        if self.failure is not None:
            raise self.failure
        return [1.0, 0.0]


class RecordingSparseRetriever:
    def __init__(
        self,
        events: list[str],
        hits: tuple[SparseHit, ...],
        *,
        failure: Exception | None = None,
    ) -> None:
        self.events = events
        self.hits = hits
        self.failure = failure
        self.scope: ResolvedSearchScope | None = None
        self.calls = 0

    async def search_sparse(
        self,
        *,
        index_alias: ActiveIndexAlias,
        query: str,
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[SparseHit, ...]:
        del index_alias, query, actor_id, top_k
        self.calls += 1
        self.scope = scope
        self.events.append("sparse")
        await asyncio.sleep(0)
        if self.failure is not None:
            raise self.failure
        return self.hits


class RecordingDenseRetriever:
    def __init__(
        self,
        events: list[str],
        hits: tuple[DenseHit, ...],
        *,
        failure: Exception | None = None,
    ) -> None:
        self.events = events
        self.hits = hits
        self.failure = failure
        self.scope: ResolvedSearchScope | None = None
        self.calls = 0

    async def search_dense(
        self,
        *,
        index_alias: ActiveIndexAlias,
        query_vector: tuple[float, ...],
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[DenseHit, ...]:
        del index_alias, actor_id, top_k
        assert query_vector == (1.0, 0.0)
        self.calls += 1
        self.scope = scope
        self.events.append("dense")
        await asyncio.sleep(0)
        if self.failure is not None:
            raise self.failure
        return self.hits


class BlockingDenseRetriever:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def search_dense(
        self,
        *,
        index_alias: ActiveIndexAlias,
        query_vector: tuple[float, ...],
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[DenseHit, ...]:
        del index_alias, query_vector, actor_id, scope, top_k
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("unreachable")


class FailingAfterDenseStartsSparseRetriever:
    def __init__(
        self,
        dense_started: asyncio.Event,
        failure: Exception,
    ) -> None:
        self.dense_started = dense_started
        self.failure = failure

    async def search_sparse(
        self,
        *,
        index_alias: ActiveIndexAlias,
        query: str,
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[SparseHit, ...]:
        del index_alias, query, actor_id, scope, top_k
        await self.dense_started.wait()
        raise self.failure


class BlockingSparseRetriever:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = False

    async def search_sparse(
        self,
        *,
        index_alias: ActiveIndexAlias,
        query: str,
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[SparseHit, ...]:
        del index_alias, query, actor_id, scope, top_k
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        raise AssertionError("unreachable")


@pytest.mark.asyncio
async def test_hybrid_resolves_scope_and_embedding_before_concurrent_branches() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope(
        (uuid4(),),
        (),
        asset_version_ids=(uuid4(),),
        index_build_ids=(uuid4(),),
    )
    duplicate = _chunk(2)
    sparse = RecordingSparseRetriever(
        events,
        (
            SparseHit(_chunk(1), rank=1, score=4.0),
            SparseHit(duplicate, rank=2, score=3.0),
        ),
    )
    dense = RecordingDenseRetriever(
        events,
        (
            DenseHit(duplicate, rank=1, score=0.9),
            DenseHit(_chunk(3), rank=2, score=0.8),
        ),
    )
    scope_resolver = RecordingScopeResolver(events, scope)
    service = HybridRetrievalService(
        scope_resolver=scope_resolver,
        embedding=RecordingEmbedding(events),
        sparse_retriever=sparse,
        dense_retriever=dense,
    )

    result = await service.search(
        actor_id=uuid4(),
        query=" query ",
        workspace_ids=scope.workspace_ids,
        folder_ids=(),
        indexing_profile_id=INDEXING_PROFILE_ID,
        retrieval_profile=_hybrid_profile(),
        index_alias=_active_alias(),
        result_limit=10,
    )

    assert events[:2] == ["scope", "embedding"]
    assert set(events[2:]) == {"sparse", "dense"}
    assert sparse.scope is scope
    assert dense.scope is scope
    assert scope_resolver.indexing_profile_ids == [INDEXING_PROFILE_ID]
    assert result[0].chunk_id == duplicate.chunk_id
    assert result[0].chunk == duplicate


@pytest.mark.asyncio
async def test_query_over_model_token_limit_is_rejected_before_scope_or_embedding() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    embedding = RecordingEmbedding(events, query_tokens=513)
    sparse = RecordingSparseRetriever(events, ())
    dense = RecordingDenseRetriever(events, ())
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=embedding,
        sparse_retriever=sparse,
        dense_retriever=dense,
    )

    with pytest.raises(AppError) as error:
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_hybrid_profile(),
            index_alias=_active_alias(),
            result_limit=10,
            query_max_tokens=512,
        )

    assert (error.value.code, error.value.status_code) == (
        "query_token_limit_exceeded",
        422,
    )
    assert events == []
    assert sparse.calls == dense.calls == 0


@pytest.mark.asyncio
async def test_active_scope_without_searchable_lifecycle_returns_empty_fail_closed() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    sparse = RecordingSparseRetriever(events, ())
    dense = RecordingDenseRetriever(events, ())
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope, allow_empty=True),
        embedding=RecordingEmbedding(events),
        sparse_retriever=sparse,
        dense_retriever=dense,
    )

    result = await service.search(
        actor_id=uuid4(),
        query="query",
        workspace_ids=scope.workspace_ids,
        folder_ids=(),
        indexing_profile_id=INDEXING_PROFILE_ID,
        retrieval_profile=_hybrid_profile(),
        index_alias=_active_alias(),
        result_limit=10,
    )

    assert result == ()
    assert events == ["scope"]
    assert sparse.calls == 0
    assert dense.calls == 0


@pytest.mark.asyncio
async def test_hybrid_branch_failure_is_not_a_dense_only_fallback() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    sparse = RecordingSparseRetriever(
        events,
        (),
        failure=SearchBackendUnavailableError("bm25 failed"),
    )
    dense = RecordingDenseRetriever(
        events,
        (DenseHit(_chunk(1), rank=1, score=0.9),),
    )
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events),
        sparse_retriever=sparse,
        dense_retriever=dense,
    )

    with pytest.raises(AppError) as error:
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_hybrid_profile(),
            index_alias=_active_alias(),
            result_limit=10,
        )

    assert (error.value.code, error.value.status_code) == (
        "hybrid_search_unavailable",
        503,
    )


@pytest.mark.asyncio
async def test_dense_operational_failure_makes_whole_hybrid_unavailable() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events),
        sparse_retriever=RecordingSparseRetriever(events, ()),
        dense_retriever=RecordingDenseRetriever(
            events,
            (),
            failure=SearchBackendUnavailableError("knn failed"),
        ),
    )

    with pytest.raises(AppError) as error:
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_hybrid_profile(),
            index_alias=_active_alias(),
            result_limit=10,
        )

    assert error.value.code == "hybrid_search_unavailable"


@pytest.mark.asyncio
async def test_bm25_profile_never_embeds_or_invokes_dense_retrieval() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    sparse = RecordingSparseRetriever(
        events,
        (SparseHit(_chunk(1), rank=1, score=4.0),),
    )
    dense = RecordingDenseRetriever(events, ())
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events),
        sparse_retriever=sparse,
        dense_retriever=dense,
    )

    result = await service.search(
        actor_id=uuid4(),
        query="query",
        workspace_ids=scope.workspace_ids,
        folder_ids=(),
        indexing_profile_id=INDEXING_PROFILE_ID,
        retrieval_profile=_bm25_profile(),
        index_alias=_active_alias(),
        result_limit=10,
    )

    assert [hit.chunk_id for hit in result] == [_chunk(1).chunk_id]
    assert events == ["scope", "sparse"]
    assert dense.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("dense_value", [None, "malformed"])
async def test_present_invalid_dense_configuration_is_not_bm25_only(
    dense_value: object,
) -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    sparse = RecordingSparseRetriever(events, ())
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events),
        sparse_retriever=sparse,
        dense_retriever=RecordingDenseRetriever(events, ()),
    )

    with pytest.raises(ValueError, match="dense must be"):
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_profile_with_dense(dense_value),
            index_alias=_active_alias(),
            result_limit=10,
        )

    assert events == []
    assert sparse.calls == 0


@pytest.mark.asyncio
async def test_hybrid_rejects_alias_for_a_different_indexing_profile() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    sparse = RecordingSparseRetriever(events, ())
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events),
        sparse_retriever=sparse,
        dense_retriever=RecordingDenseRetriever(events, ()),
    )

    with pytest.raises(ValueError, match="indexing profile"):
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_hybrid_profile(uuid4()),
            index_alias=_active_alias(),
            result_limit=10,
        )

    assert events == []
    assert sparse.calls == 0


@pytest.mark.asyncio
async def test_bm25_rejects_alias_for_a_different_selected_indexing_profile() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    sparse = RecordingSparseRetriever(events, ())
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events),
        sparse_retriever=sparse,
        dense_retriever=RecordingDenseRetriever(events, ()),
    )

    with pytest.raises(ValueError, match="indexing profile"):
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_bm25_profile(),
            index_alias=_active_alias(uuid4()),
            result_limit=10,
        )

    assert events == []
    assert sparse.calls == 0


@pytest.mark.asyncio
async def test_operational_embedding_failure_makes_hybrid_unavailable() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(
            events,
            failure=QueryEmbeddingUnavailableError("model runtime unavailable"),
        ),
        sparse_retriever=RecordingSparseRetriever(events, ()),
        dense_retriever=RecordingDenseRetriever(events, ()),
    )

    with pytest.raises(AppError) as error:
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_hybrid_profile(),
            index_alias=_active_alias(),
            result_limit=10,
        )

    assert error.value.code == "hybrid_search_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [
        AssertionError("assert defect"),
        TypeError("type defect"),
        ValueError("value defect"),
        RuntimeError("untyped runtime defect"),
    ],
)
async def test_embedding_programming_defects_propagate_unchanged(
    failure: Exception,
) -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events, failure=failure),
        sparse_retriever=RecordingSparseRetriever(events, ()),
        dense_retriever=RecordingDenseRetriever(events, ()),
    )

    with pytest.raises(type(failure)) as error:
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_hybrid_profile(),
            index_alias=_active_alias(),
            result_limit=10,
        )

    assert error.value is failure


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure",
    [AssertionError("assert defect"), TypeError("type defect"), ValueError("value defect")],
)
async def test_hybrid_branch_programming_defects_remain_in_exception_group(
    failure: Exception,
) -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events),
        sparse_retriever=RecordingSparseRetriever(events, (), failure=failure),
        dense_retriever=RecordingDenseRetriever(events, ()),
    )

    with pytest.raises(ExceptionGroup) as error:
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_hybrid_profile(),
            index_alias=_active_alias(),
            result_limit=10,
        )

    assert failure in _exception_leaves(error.value)


@pytest.mark.asyncio
async def test_mixed_operational_and_programming_exception_group_propagates() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    operational = SearchBackendUnavailableError("backend unavailable")
    programming = TypeError("branch defect")
    mixed = ExceptionGroup("mixed", [operational, programming])
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events),
        sparse_retriever=RecordingSparseRetriever(events, (), failure=mixed),
        dense_retriever=RecordingDenseRetriever(events, ()),
    )

    with pytest.raises(ExceptionGroup) as error:
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_hybrid_profile(),
            index_alias=_active_alias(),
            result_limit=10,
        )

    leaves = _exception_leaves(error.value)
    assert operational in leaves
    assert programming in leaves


@pytest.mark.asyncio
async def test_bm25_programming_defect_propagates_unchanged() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    failure = ValueError("response defect")
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events),
        sparse_retriever=RecordingSparseRetriever(events, (), failure=failure),
        dense_retriever=RecordingDenseRetriever(events, ()),
    )

    with pytest.raises(ValueError) as error:
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_bm25_profile(),
            index_alias=_active_alias(),
            result_limit=10,
        )

    assert error.value is failure


@pytest.mark.asyncio
async def test_rrf_provenance_defect_propagates_as_value_error() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    sparse_chunk = _chunk(1)
    dense_chunk = _chunk(1)
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events),
        sparse_retriever=RecordingSparseRetriever(
            events,
            (SparseHit(sparse_chunk, rank=1, score=1.0),),
        ),
        dense_retriever=RecordingDenseRetriever(
            events,
            (DenseHit(dense_chunk, rank=1, score=1.0),),
        ),
    )

    with pytest.raises(ValueError, match="provenance"):
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_hybrid_profile(),
            index_alias=_active_alias(),
            result_limit=10,
        )


@pytest.mark.asyncio
async def test_operational_branch_failure_cancels_taskgroup_sibling() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    dense = BlockingDenseRetriever()
    sparse = FailingAfterDenseStartsSparseRetriever(
        dense.started,
        SearchBackendUnavailableError("backend unavailable"),
    )
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events),
        sparse_retriever=sparse,
        dense_retriever=dense,
    )

    with pytest.raises(AppError) as error:
        await service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_hybrid_profile(),
            index_alias=_active_alias(),
            result_limit=10,
        )

    assert error.value.code == "hybrid_search_unavailable"
    assert dense.cancelled is True


@pytest.mark.asyncio
async def test_caller_cancellation_propagates_unchanged() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    dense = BlockingDenseRetriever()
    sparse = BlockingSparseRetriever()
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events),
        sparse_retriever=sparse,
        dense_retriever=dense,
    )

    search_task = asyncio.create_task(
        service.search(
            actor_id=uuid4(),
            query="query",
            workspace_ids=scope.workspace_ids,
            folder_ids=(),
            indexing_profile_id=INDEXING_PROFILE_ID,
            retrieval_profile=_hybrid_profile(),
            index_alias=_active_alias(),
            result_limit=10,
        )
    )
    await asyncio.gather(sparse.started.wait(), dense.started.wait())
    search_task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await search_task

    assert sparse.cancelled is True
    assert dense.cancelled is True
