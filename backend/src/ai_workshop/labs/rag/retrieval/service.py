import asyncio
from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from ai_workshop.labs.rag.embeddings.contracts import EmbeddingPort
from ai_workshop.labs.rag.models.domain import FrozenJsonValue, Profile, ProfileKind
from ai_workshop.labs.rag.retrieval.domain import (
    DenseHit,
    FusedHit,
    ResolvedSearchScope,
    SparseHit,
)
from ai_workshop.labs.rag.retrieval.rrf import rrf_fuse
from ai_workshop.shared.errors import AppError


class SearchScopeResolverPort(Protocol):
    async def resolve(
        self,
        *,
        actor_id: UUID,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
    ) -> ResolvedSearchScope: ...


class SparseRetrieverPort(Protocol):
    async def search_sparse(
        self,
        *,
        index_alias: str,
        query: str,
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[SparseHit, ...]: ...


class DenseRetrieverPort(Protocol):
    async def search_dense(
        self,
        *,
        index_alias: str,
        query_vector: tuple[float, ...],
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[DenseHit, ...]: ...


class HybridRetrievalService:
    def __init__(
        self,
        *,
        scope_resolver: SearchScopeResolverPort,
        embedding: EmbeddingPort,
        sparse_retriever: SparseRetrieverPort,
        dense_retriever: DenseRetrieverPort,
    ) -> None:
        self.scope_resolver = scope_resolver
        self.embedding = embedding
        self.sparse_retriever = sparse_retriever
        self.dense_retriever = dense_retriever

    async def search(
        self,
        *,
        actor_id: UUID,
        query: str,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
        retrieval_profile: Profile,
        index_alias: str,
        result_limit: int,
    ) -> tuple[FusedHit, ...]:
        clean_query = query.strip()
        if not clean_query:
            raise AppError("invalid_query", "A non-empty search query is required.", 422)
        if result_limit < 1:
            raise AppError("invalid_result_limit", "The result limit must be positive.", 422)
        bm25_top_k, dense_top_k, rrf_k = _retrieval_settings(retrieval_profile)

        scope = await self.scope_resolver.resolve(
            actor_id=actor_id,
            workspace_ids=workspace_ids,
            folder_ids=folder_ids,
        )

        if dense_top_k is None:
            try:
                sparse_hits = await self.sparse_retriever.search_sparse(
                    index_alias=index_alias,
                    query=clean_query,
                    actor_id=actor_id,
                    scope=scope,
                    top_k=bm25_top_k,
                )
            except Exception as exc:
                raise AppError(
                    "bm25_search_unavailable",
                    "BM25 search is temporarily unavailable.",
                    503,
                ) from exc
            return rrf_fuse(sparse_hits, (), k=60)[:result_limit]

        try:
            query_vector = tuple(self.embedding.encode_query(clean_query))
        except Exception as exc:
            raise AppError(
                "hybrid_search_unavailable",
                "Hybrid search is temporarily unavailable.",
                503,
            ) from exc

        try:
            async with asyncio.TaskGroup() as group:
                sparse_task = group.create_task(
                    self.sparse_retriever.search_sparse(
                        index_alias=index_alias,
                        query=clean_query,
                        actor_id=actor_id,
                        scope=scope,
                        top_k=bm25_top_k,
                    )
                )
                dense_task = group.create_task(
                    self.dense_retriever.search_dense(
                        index_alias=index_alias,
                        query_vector=query_vector,
                        actor_id=actor_id,
                        scope=scope,
                        top_k=dense_top_k,
                    )
                )
        except ExceptionGroup as exc:
            raise AppError(
                "hybrid_search_unavailable",
                "Hybrid search is temporarily unavailable.",
                503,
            ) from exc

        try:
            return rrf_fuse(
                sparse_task.result(),
                dense_task.result(),
                k=rrf_k,
            )[:result_limit]
        except ValueError as exc:
            raise AppError(
                "hybrid_search_unavailable",
                "Hybrid search is temporarily unavailable.",
                503,
            ) from exc


def _retrieval_settings(profile: Profile) -> tuple[int, int | None, int]:
    if profile.kind is not ProfileKind.RETRIEVAL:
        raise ValueError("Search requires an immutable retrieval profile version.")
    bm25 = _mapping(profile.config.get("bm25"), "bm25")
    bm25_top_k = _positive_integer(bm25.get("top_k"), "bm25.top_k")
    dense_value = profile.config.get("dense")
    if dense_value is None:
        return bm25_top_k, None, 60
    dense = _mapping(dense_value, "dense")
    dense_top_k = _positive_integer(dense.get("top_k"), "dense.top_k")
    rrf = _mapping(profile.config.get("rrf"), "rrf")
    rrf_k = _non_negative_integer(rrf.get("k"), "rrf.k")
    if rrf_k != 60:
        raise ValueError("The first hybrid retrieval baseline requires RRF k=60.")
    return bm25_top_k, dense_top_k, rrf_k


def _mapping(
    value: FrozenJsonValue | None,
    name: str,
) -> Mapping[str, FrozenJsonValue]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be an immutable configuration mapping.")
    return value


def _positive_integer(value: object, name: str) -> int:
    result = _non_negative_integer(value, name)
    if result < 1:
        raise ValueError(f"{name} must be positive.")
    return result


def _non_negative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer.")
    return value
