import asyncio
from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from ai_workshop.labs.rag.embeddings.contracts import EmbeddingPort
from ai_workshop.labs.rag.models.domain import FrozenJsonValue, Profile, ProfileKind
from ai_workshop.labs.rag.retrieval.domain import (
    ActiveIndexAlias,
    DenseHit,
    FusedHit,
    QueryEmbeddingUnavailableError,
    ResolvedSearchScope,
    SearchBackendUnavailableError,
    SparseHit,
)
from ai_workshop.labs.rag.retrieval.query_embedding import RetrievalQueryEmbedding
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
        index_alias: ActiveIndexAlias,
        query: str,
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[SparseHit, ...]: ...


class DenseRetrieverPort(Protocol):
    async def search_dense(
        self,
        *,
        index_alias: ActiveIndexAlias,
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
        self.embedding = RetrievalQueryEmbedding(embedding)
        self.sparse_retriever = sparse_retriever
        self.dense_retriever = dense_retriever

    async def search(
        self,
        *,
        actor_id: UUID,
        query: str,
        workspace_ids: tuple[UUID, ...],
        folder_ids: tuple[UUID, ...],
        indexing_profile_id: UUID,
        retrieval_profile: Profile,
        index_alias: ActiveIndexAlias,
        result_limit: int,
    ) -> tuple[FusedHit, ...]:
        clean_query = query.strip()
        if not clean_query:
            raise AppError("invalid_query", "A non-empty search query is required.", 422)
        if result_limit < 1:
            raise AppError("invalid_result_limit", "The result limit must be positive.", 422)
        bm25_top_k, dense_top_k, rrf_k = _retrieval_settings(retrieval_profile)
        _validate_active_alias(
            retrieval_profile,
            indexing_profile_id,
            index_alias,
            dense_top_k=dense_top_k,
        )

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
            except SearchBackendUnavailableError as exc:
                raise AppError(
                    "bm25_search_unavailable",
                    "BM25 search is temporarily unavailable.",
                    503,
                ) from exc
            return rrf_fuse(sparse_hits, (), k=60)[:result_limit]

        try:
            query_vector = tuple(self.embedding.encode_query(clean_query))
        except QueryEmbeddingUnavailableError as exc:
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
            if not _only_search_backend_failures(exc):
                raise
            raise AppError(
                "hybrid_search_unavailable",
                "Hybrid search is temporarily unavailable.",
                503,
            ) from exc

        return rrf_fuse(
            sparse_task.result(),
            dense_task.result(),
            k=rrf_k,
        )[:result_limit]


def _retrieval_settings(profile: Profile) -> tuple[int, int | None, int]:
    if profile.kind is not ProfileKind.RETRIEVAL:
        raise ValueError("Search requires an immutable retrieval profile version.")
    bm25 = _mapping(profile.config.get("bm25"), "bm25")
    bm25_top_k = _positive_integer(bm25.get("top_k"), "bm25.top_k")
    if "dense" not in profile.config:
        return bm25_top_k, None, 60
    dense_value = profile.config["dense"]
    dense = _mapping(dense_value, "dense")
    dense_top_k = _positive_integer(dense.get("top_k"), "dense.top_k")
    rrf = _mapping(profile.config.get("rrf"), "rrf")
    rrf_k = _non_negative_integer(rrf.get("k"), "rrf.k")
    if rrf_k != 60:
        raise ValueError("The first hybrid retrieval baseline requires RRF k=60.")
    return bm25_top_k, dense_top_k, rrf_k


def _validate_active_alias(
    profile: Profile,
    indexing_profile_id: UUID,
    index_alias: ActiveIndexAlias,
    *,
    dense_top_k: int | None,
) -> None:
    if not isinstance(index_alias, ActiveIndexAlias):
        raise ValueError("Retrieval requires a resolved active index alias.")
    if index_alias.indexing_profile_id != indexing_profile_id:
        raise ValueError(
            "The active index alias must match the selected indexing profile."
        )
    profile_id = profile.config.get("indexing_profile_id")
    if profile_id is None and dense_top_k is None:
        return
    if not isinstance(profile_id, str):
        raise ValueError("A retrieval profile requires a valid indexing profile UUID.")
    try:
        expected_profile_id = UUID(profile_id)
    except ValueError as exc:
        raise ValueError(
            "A retrieval profile requires a valid indexing profile UUID."
        ) from exc
    if indexing_profile_id != expected_profile_id:
        raise ValueError(
            "The selected indexing profile must match the retrieval profile reference."
        )


def _only_search_backend_failures(error: BaseException) -> bool:
    if isinstance(error, BaseExceptionGroup):
        return all(_only_search_backend_failures(item) for item in error.exceptions)
    return isinstance(error, SearchBackendUnavailableError)


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
