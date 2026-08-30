import asyncio
from typing import NoReturn
from uuid import UUID, uuid4

import pytest

from ai_workshop.labs.rag.models.domain import Profile, ProfileKind
from ai_workshop.labs.rag.retrieval.domain import (
    DenseHit,
    ResolvedSearchScope,
    RetrievedChunk,
    SparseHit,
)
from ai_workshop.labs.rag.retrieval.service import HybridRetrievalService
from ai_workshop.shared.errors import AppError


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


def _hybrid_profile() -> Profile:
    return Profile.create(
        kind=ProfileKind.RETRIEVAL,
        name="hybrid",
        version=1,
        config={
            "bm25": {"top_k": 3},
            "dense": {"top_k": 3},
            "rrf": {"k": 60},
            "indexing_profile_id": str(uuid4()),
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


class RecordingScopeResolver:
    def __init__(self, events: list[str], scope: ResolvedSearchScope) -> None:
        self.events = events
        self.scope = scope

    async def resolve(
        self,
        *,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
    ) -> ResolvedSearchScope:
        del actor_id, workspace_ids, folder_ids
        self.events.append("scope")
        return self.scope


class RecordingEmbedding:
    dimension = 2

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def count_query_tokens(self, text: str) -> int:
        return len(text.split())

    def encode_documents(self, texts: object) -> NoReturn:
        del texts
        raise AssertionError("document embedding is not part of retrieval")

    def encode_query(self, text: str) -> list[float]:
        assert text == "query"
        self.events.append("embedding")
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
        index_alias: str,
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
    def __init__(self, events: list[str], hits: tuple[DenseHit, ...]) -> None:
        self.events = events
        self.hits = hits
        self.scope: ResolvedSearchScope | None = None
        self.calls = 0

    async def search_dense(
        self,
        *,
        index_alias: str,
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
        return self.hits


@pytest.mark.asyncio
async def test_hybrid_resolves_scope_and_embedding_before_concurrent_branches() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
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
    service = HybridRetrievalService(
        scope_resolver=RecordingScopeResolver(events, scope),
        embedding=RecordingEmbedding(events),
        sparse_retriever=sparse,
        dense_retriever=dense,
    )

    result = await service.search(
        actor_id=uuid4(),
        query=" query ",
        workspace_ids=scope.workspace_ids,
        folder_ids=(),
        retrieval_profile=_hybrid_profile(),
        index_alias="profile-active",
        result_limit=10,
    )

    assert events[:2] == ["scope", "embedding"]
    assert set(events[2:]) == {"sparse", "dense"}
    assert sparse.scope is scope
    assert dense.scope is scope
    assert result[0].chunk_id == duplicate.chunk_id
    assert result[0].chunk == duplicate


@pytest.mark.asyncio
async def test_hybrid_branch_failure_is_not_a_dense_only_fallback() -> None:
    events: list[str] = []
    scope = ResolvedSearchScope((uuid4(),), ())
    sparse = RecordingSparseRetriever(events, (), failure=RuntimeError("bm25 failed"))
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
            retrieval_profile=_hybrid_profile(),
            index_alias="profile-active",
            result_limit=10,
        )

    assert (error.value.code, error.value.status_code) == (
        "hybrid_search_unavailable",
        503,
    )


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
        retrieval_profile=_bm25_profile(),
        index_alias="profile-active",
        result_limit=10,
    )

    assert [hit.chunk_id for hit in result] == [_chunk(1).chunk_id]
    assert events == ["scope", "sparse"]
    assert dense.calls == 0
