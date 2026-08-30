from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from ai_workshop.labs.rag.highlighting.domain import (
    EvidenceSelection,
    EvidenceSource,
)
from ai_workshop.labs.rag.highlighting.service import EvidenceSelector
from ai_workshop.labs.rag.retrieval.domain import FusedHit
from ai_workshop.labs.rag.retrieval.service import (
    DenseRetrieverPort,
    HybridRetrievalService,
    SearchScopeResolverPort,
    SparseRetrieverPort,
)
from ai_workshop.labs.rag.search.configuration_port import (
    ResolvedSearchConfiguration,
    SearchConfigurationResolverPort,
)
from ai_workshop.shared.errors import AppError

if TYPE_CHECKING:
    from ai_workshop.labs.rag.search.schemas import SearchRequest


class SearchSourceResolverPort(Protocol):
    async def resolve(
        self,
        *,
        actor_id: UUID,
        indexing_profile_id: UUID,
        hits: tuple[FusedHit, ...],
    ) -> tuple[EvidenceSource, ...]: ...


@dataclass(frozen=True, slots=True)
class RelatedSource:
    source: EvidenceSource


@dataclass(frozen=True, slots=True)
class SearchResult:
    selection: EvidenceSelection
    configuration: ResolvedSearchConfiguration
    related_sources: tuple[RelatedSource, ...]


class SearchApplicationService:
    def __init__(
        self,
        *,
        configuration_resolver: SearchConfigurationResolverPort,
        scope_resolver: SearchScopeResolverPort,
        sparse_retriever: SparseRetrieverPort,
        dense_retriever: DenseRetrieverPort,
        source_resolver: SearchSourceResolverPort,
    ) -> None:
        self.configuration_resolver = configuration_resolver
        self.scope_resolver = scope_resolver
        self.sparse_retriever = sparse_retriever
        self.dense_retriever = dense_retriever
        self.source_resolver = source_resolver

    async def search(self, *, actor_id: UUID, request: SearchRequest) -> SearchResult:
        configuration = await self.configuration_resolver.resolve(
            request.configuration_id,
            actor_id,
        )
        policy = configuration.answer_policy
        if configuration.answer_policy_version_id is None or policy is None:
            raise AppError(
                "answer_policy_missing",
                "The selected search configuration has no answer policy version.",
                409,
            )

        retrieval = HybridRetrievalService(
            scope_resolver=self.scope_resolver,
            embedding=configuration.embedding,
            sparse_retriever=self.sparse_retriever,
            dense_retriever=self.dense_retriever,
        )
        hits = await retrieval.search(
            actor_id=actor_id,
            query=request.query,
            workspace_ids=tuple(request.workspace_ids),
            folder_ids=tuple(request.folder_ids),
            indexing_profile_id=configuration.indexing_profile_id,
            retrieval_profile=configuration.retrieval_profile,
            index_alias=configuration.active_index_alias,
            result_limit=request.top_k,
        )
        sources = await self.source_resolver.resolve(
            actor_id=actor_id,
            indexing_profile_id=configuration.indexing_profile_id,
            hits=hits,
        )
        selection = EvidenceSelector(configuration.embedding).select(
            query=request.query.strip(),
            sources=sources,
            policy=policy,
        )
        return SearchResult(
            selection=selection,
            configuration=configuration,
            related_sources=_related_sources(sources, selection),
        )


def _related_sources(
    sources: tuple[EvidenceSource, ...],
    selection: EvidenceSelection,
) -> tuple[RelatedSource, ...]:
    selected_version_ids = {
        item.source.chunk.asset_version_id
        for item in (
            *((selection.answer,) if selection.answer is not None else ()),
            *selection.conflicts,
        )
    }
    seen: set[UUID] = set()
    related: list[RelatedSource] = []
    for source in sources:
        version_id = source.chunk.asset_version_id
        if version_id in selected_version_ids or version_id in seen:
            continue
        seen.add(version_id)
        related.append(RelatedSource(source))
    return tuple(related)
