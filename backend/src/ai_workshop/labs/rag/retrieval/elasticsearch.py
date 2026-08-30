from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from elasticsearch import ApiError, AsyncElasticsearch, TransportError

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.retrieval.domain import (
    ActiveIndexAlias,
    DenseHit,
    ResolvedSearchScope,
    RetrievedChunk,
    SearchBackendUnavailableError,
    SparseHit,
)

RETRIEVAL_SOURCE_FIELDS = (
    "chunk_id",
    "projection_id",
    "asset_version_id",
    "workspace_id",
    "folder_id",
    "index_build_id",
    "title",
    "section_path",
    "text",
    "evidence_units",
)


def build_scope_filter(
    actor_id: UUID,
    scope: ResolvedSearchScope,
) -> list[dict[str, object]]:
    filters: list[dict[str, object]] = [
        {"terms": {"workspace_id": [str(item) for item in scope.workspace_ids]}},
        {"term": {"allowed_user_ids": str(actor_id)}},
    ]
    if scope.folder_ids:
        filters.append({"terms": {"folder_id": [str(item) for item in scope.folder_ids]}})
    if scope.ready_only:
        filters.append({"term": {"status": "ready"}})
    return filters


class ElasticsearchSparseRetriever:
    def __init__(self, client: AsyncElasticsearch) -> None:
        self.client = client

    async def search_sparse(
        self,
        *,
        index_alias: ActiveIndexAlias,
        query: str,
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[SparseHit, ...]:
        _validate_search(index_alias, scope, top_k)
        try:
            response = await self.client.search(
                index=index_alias.name,
                query={
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": ["text", "title", "section_path"],
                                }
                            }
                        ],
                        "filter": build_scope_filter(actor_id, scope),
                    }
                },
                size=top_k,
                source={"includes": list(RETRIEVAL_SOURCE_FIELDS)},
            )
        except (ApiError, TransportError) as exc:
            raise SearchBackendUnavailableError(
                "Elasticsearch sparse retrieval is unavailable."
            ) from exc
        return tuple(
            SparseHit(_parse_chunk(hit), rank=rank, score=_score(hit))
            for rank, hit in enumerate(_raw_hits(response), start=1)
        )


class ElasticsearchDenseRetriever:
    def __init__(self, client: AsyncElasticsearch) -> None:
        self.client = client

    async def search_dense(
        self,
        *,
        index_alias: ActiveIndexAlias,
        query_vector: tuple[float, ...],
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[DenseHit, ...]:
        _validate_search(index_alias, scope, top_k)
        if not query_vector:
            raise ValueError("Dense retrieval requires a query vector.")
        try:
            response = await self.client.search(
                index=index_alias.name,
                knn={
                    "field": "embedding",
                    "query_vector": list(query_vector),
                    "k": top_k,
                    "num_candidates": top_k,
                    "filter": {"bool": {"filter": build_scope_filter(actor_id, scope)}},
                },
                size=top_k,
                source={"includes": list(RETRIEVAL_SOURCE_FIELDS)},
            )
        except (ApiError, TransportError) as exc:
            raise SearchBackendUnavailableError(
                "Elasticsearch dense retrieval is unavailable."
            ) from exc
        return tuple(
            DenseHit(_parse_chunk(hit), rank=rank, score=_score(hit))
            for rank, hit in enumerate(_raw_hits(response), start=1)
        )


def _validate_search(
    index_alias: ActiveIndexAlias,
    scope: ResolvedSearchScope,
    top_k: int,
) -> None:
    if not isinstance(index_alias, ActiveIndexAlias):
        raise ValueError("Retrieval requires a resolved active index alias.")
    if not scope.workspace_ids:
        raise ValueError("Retrieval requires a non-empty authorized workspace scope.")
    if not scope.active_only:
        raise ValueError("Normal retrieval requires the active profile index alias.")
    if not scope.ready_only:
        raise ValueError("Normal retrieval requires READY projections.")
    if top_k < 1:
        raise ValueError("Retrieval top_k must be positive.")


def _raw_hits(response: Any) -> Sequence[dict[str, Any]]:
    return cast(Sequence[dict[str, Any]], response["hits"]["hits"])


def _score(hit: dict[str, Any]) -> float:
    score = hit.get("_score")
    return float(score) if score is not None else 0.0


def _parse_chunk(hit: dict[str, Any]) -> RetrievedChunk:
    source = cast(dict[str, Any], hit["_source"])
    chunk_id = UUID(str(source["chunk_id"]))
    projection_id = UUID(str(source["projection_id"]))
    evidence = tuple(
        _parse_evidence(item, chunk_id=chunk_id, projection_id=projection_id)
        for item in cast(list[dict[str, Any]], source.get("evidence_units", []))
    )
    folder_value = source.get("folder_id")
    return RetrievedChunk(
        chunk_id=chunk_id,
        projection_id=projection_id,
        asset_version_id=UUID(str(source["asset_version_id"])),
        workspace_id=UUID(str(source["workspace_id"])),
        folder_id=UUID(str(folder_value)) if folder_value is not None else None,
        index_build_id=UUID(str(source["index_build_id"])),
        title=str(source["title"]),
        section_path=tuple(str(item) for item in source["section_path"]),
        text=str(source["text"]),
        evidence_units=evidence,
    )


def _parse_evidence(
    source: dict[str, Any],
    *,
    chunk_id: UUID,
    projection_id: UUID,
) -> EvidenceUnit:
    stored_chunk_id = UUID(str(source["chunk_id"]))
    stored_projection_id = UUID(str(source["projection_id"]))
    if stored_chunk_id != chunk_id or stored_projection_id != projection_id:
        raise ValueError("Evidence provenance does not match its retrieved chunk.")
    bbox_value = source.get("bbox")
    bbox = None
    if bbox_value is not None:
        values = tuple(
            float(cast(str | int | float, value))
            for value in cast(Sequence[object], bbox_value)
        )
        if len(values) != 4:
            raise ValueError("Evidence bounding boxes require four values.")
        bbox = values
    return EvidenceUnit(
        id=UUID(str(source["id"])),
        chunk_id=stored_chunk_id,
        ordinal=int(source["ordinal"]),
        text=str(source["text"]),
        location=SourceLocation(
            element_id=UUID(str(source["element_id"])),
            page=int(source["page"]) if source.get("page") is not None else None,
            char_start=int(source["char_start"]),
            char_end=int(source["char_end"]),
            bbox=bbox,
        ),
        projection_id=stored_projection_id,
    )
