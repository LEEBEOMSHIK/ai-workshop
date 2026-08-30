from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

from elasticsearch import ApiError, AsyncElasticsearch, TransportError

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.retrieval.domain import (
    ActiveIndexAlias,
    DenseHit,
    FrozenIndexTarget,
    ResolvedSearchScope,
    RetrievedChunk,
    SearchBackendUnavailableError,
    SearchIndexTarget,
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


async def require_concrete_frozen_indices(
    client: AsyncElasticsearch,
    target: FrozenIndexTarget,
) -> None:
    """Fail closed unless every frozen target resolves as its one concrete index."""

    for index_name in target.index_names:
        try:
            response = cast(
                dict[str, Any],
                await client.indices.resolve_index(
                    name=index_name,
                    expand_wildcards="open",
                ),
            )
        except ApiError as exc:
            if exc.meta.status == 404:
                raise ValueError("A frozen concrete physical index is missing.") from exc
            if not _is_operational_backend_error(exc):
                raise
            raise SearchBackendUnavailableError(
                "Elasticsearch frozen-index resolution is unavailable."
            ) from exc
        except TransportError as exc:
            raise SearchBackendUnavailableError(
                "Elasticsearch frozen-index resolution is unavailable."
            ) from exc
        indices = cast(list[dict[str, Any]], response.get("indices", []))
        aliases = cast(list[dict[str, Any]], response.get("aliases", []))
        data_streams = cast(list[dict[str, Any]], response.get("data_streams", []))
        if (
            aliases
            or data_streams
            or len(indices) != 1
            or str(indices[0].get("name")) != index_name
        ):
            raise ValueError(
                "A frozen target must resolve to one exact concrete physical index."
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
    if scope.asset_version_ids:
        filters.append(
            {
                "terms": {
                    "asset_version_id": [str(item) for item in scope.asset_version_ids]
                }
            }
        )
    if scope.index_build_ids:
        filters.append(
            {
                "terms": {
                    "index_build_id": [str(item) for item in scope.index_build_ids]
                }
            }
        )
    return filters


class ElasticsearchSparseRetriever:
    def __init__(self, client: AsyncElasticsearch) -> None:
        self.client = client

    async def search_sparse(
        self,
        *,
        index_alias: SearchIndexTarget,
        query: str,
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[SparseHit, ...]:
        _validate_search(index_alias, scope, top_k)
        try:
            responses = [
                await self.client.search(
                    index=index_name,
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
                for index_name in _exact_index_names(index_alias)
            ]
        except (ApiError, TransportError) as exc:
            if not _is_operational_backend_error(exc):
                raise
            raise SearchBackendUnavailableError(
                "Elasticsearch sparse retrieval is unavailable."
            ) from exc
        raw_hits = sorted(
            (hit for response in responses for hit in _raw_hits(response)),
            key=_score,
            reverse=True,
        )[:top_k]
        return tuple(
            SparseHit(_parse_chunk(hit), rank=rank, score=_score(hit))
            for rank, hit in enumerate(raw_hits, start=1)
        )


class ElasticsearchDenseRetriever:
    def __init__(self, client: AsyncElasticsearch) -> None:
        self.client = client

    async def search_dense(
        self,
        *,
        index_alias: SearchIndexTarget,
        query_vector: tuple[float, ...],
        actor_id: UUID,
        scope: ResolvedSearchScope,
        top_k: int,
    ) -> tuple[DenseHit, ...]:
        _validate_search(index_alias, scope, top_k)
        if not query_vector:
            raise ValueError("Dense retrieval requires a query vector.")
        try:
            responses = [
                await self.client.search(
                    index=index_name,
                    knn={
                        "field": "embedding",
                        "query_vector": list(query_vector),
                        "k": top_k,
                        "num_candidates": top_k,
                        "filter": {
                            "bool": {"filter": build_scope_filter(actor_id, scope)}
                        },
                    },
                    size=top_k,
                    source={"includes": list(RETRIEVAL_SOURCE_FIELDS)},
                )
                for index_name in _exact_index_names(index_alias)
            ]
        except (ApiError, TransportError) as exc:
            if not _is_operational_backend_error(exc):
                raise
            raise SearchBackendUnavailableError(
                "Elasticsearch dense retrieval is unavailable."
            ) from exc
        raw_hits = sorted(
            (hit for response in responses for hit in _raw_hits(response)),
            key=_score,
            reverse=True,
        )[:top_k]
        return tuple(
            DenseHit(_parse_chunk(hit), rank=rank, score=_score(hit))
            for rank, hit in enumerate(raw_hits, start=1)
        )


def _validate_search(
    index_alias: SearchIndexTarget,
    scope: ResolvedSearchScope,
    top_k: int,
) -> None:
    if not isinstance(index_alias, (ActiveIndexAlias, FrozenIndexTarget)):
        raise ValueError("Retrieval requires a resolved index target.")
    if not scope.workspace_ids:
        raise ValueError("Retrieval requires a non-empty authorized workspace scope.")
    if isinstance(index_alias, ActiveIndexAlias) and not scope.active_only:
        raise ValueError("Normal retrieval requires the active profile index alias.")
    if isinstance(index_alias, FrozenIndexTarget) and scope.active_only:
        raise ValueError("Frozen evaluation retrieval cannot use active-only semantics.")
    if not scope.ready_only:
        raise ValueError("Normal retrieval requires READY projections.")
    if top_k < 1:
        raise ValueError("Retrieval top_k must be positive.")


def _exact_index_names(index_target: SearchIndexTarget) -> tuple[str, ...]:
    if isinstance(index_target, FrozenIndexTarget):
        return index_target.index_names
    return (index_target.name,)


def _is_operational_backend_error(error: ApiError | TransportError) -> bool:
    if isinstance(error, TransportError):
        return True
    status = error.meta.status
    return status == 429 or 500 <= status < 600


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
