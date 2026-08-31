import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from elasticsearch import ApiError, AsyncElasticsearch, TransportError

from ai_workshop.labs.rag.documents.domain import EvidenceUnit, SourceLocation
from ai_workshop.labs.rag.retrieval.domain import (
    ActiveIndexAlias,
    DenseHit,
    FrozenIndexIdentity,
    FrozenIndexTarget,
    ResolvedSearchScope,
    RetrievedChunk,
    SearchBackendUnavailableError,
    SearchIndexTarget,
    SparseHit,
)

logger = logging.getLogger(__name__)


class FrozenIndexDriftError(ValueError):
    """The physical index no longer matches its frozen immutable identity."""


class FrozenIndexReindexRequiredError(FrozenIndexDriftError):
    """A legacy physical index lacks the metadata required for safe evaluation."""


class PointInTimeCleanupError(RuntimeError):
    """Closing an evaluation point-in-time failed."""


@dataclass(frozen=True, slots=True)
class FrozenIndexDescription:
    identity: FrozenIndexIdentity


class ElasticsearchFrozenIndexInspector:
    def __init__(self, client: AsyncElasticsearch) -> None:
        self.client = client

    async def describe(self, index_name: str) -> FrozenIndexIdentity:
        return (await describe_frozen_index(self.client, index_name)).identity

RETRIEVAL_SOURCE_FIELDS = (
    "chunk_id",
    "projection_id",
    "asset_version_id",
    "workspace_id",
    "folder_id",
    "index_build_id",
    "indexing_profile_id",
    "rag_mapping_version",
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

    for expected in target.identities:
        actual = await describe_frozen_index(client, expected.index_name)
        _require_same_frozen_identity(expected, actual.identity)


async def describe_frozen_index(
    client: AsyncElasticsearch,
    index_name: str,
) -> FrozenIndexDescription:
    """Resolve one concrete index and return its Elasticsearch UUID/RAG metadata."""

    try:
        response = cast(
            dict[str, Any],
            await client.indices.resolve_index(
                name=index_name,
                expand_wildcards="open",
            ),
        )
        indices = cast(list[dict[str, Any]], response.get("indices", []))
        aliases = cast(list[dict[str, Any]], response.get("aliases", []))
        data_streams = cast(list[dict[str, Any]], response.get("data_streams", []))
        if (
            aliases
            or data_streams
            or len(indices) != 1
            or str(indices[0].get("name")) != index_name
        ):
            raise FrozenIndexDriftError(
                "A frozen target must resolve to one exact concrete physical index."
            )
        metadata_response = cast(
            dict[str, Any], await client.indices.get(index=index_name)
        )
    except ApiError as exc:
        if exc.meta.status == 404:
            raise FrozenIndexDriftError(
                "A frozen concrete physical index is missing."
            ) from exc
        if not _is_operational_backend_error(exc):
            raise
        raise SearchBackendUnavailableError(
            "Elasticsearch frozen-index resolution is unavailable."
        ) from exc
    except TransportError as exc:
        raise SearchBackendUnavailableError(
            "Elasticsearch frozen-index resolution is unavailable."
        ) from exc
    if set(metadata_response) != {index_name}:
        raise FrozenIndexDriftError(
            "A frozen target metadata lookup did not return its exact physical name."
        )
    raw = cast(dict[str, Any], metadata_response[index_name])
    settings = cast(dict[str, Any], raw.get("settings", {}))
    index_settings = cast(dict[str, Any], settings.get("index", {}))
    mappings = cast(dict[str, Any], raw.get("mappings", {}))
    raw_meta = mappings.get("_meta")
    if not isinstance(raw_meta, dict) or not isinstance(raw_meta.get("rag"), dict):
        raise FrozenIndexReindexRequiredError(
            "The physical index has no mappings._meta.rag descriptor; reindex is required."
        )
    rag = cast(dict[str, Any], raw_meta["rag"])
    required_mapping = {
        "mapping_version",
        "index_build_id",
        "projection_id",
        "indexing_profile_id",
        "vector_dimension",
    }
    if (
        set(rag) != required_mapping
        or not isinstance(index_settings.get("uuid"), str)
        or type(rag["mapping_version"]) is not int
        or type(rag["vector_dimension"]) is not int
        or not all(
            isinstance(rag[key], str)
            for key in ("index_build_id", "projection_id", "indexing_profile_id")
        )
    ):
        raise FrozenIndexReindexRequiredError(
            "The physical index has incomplete or mistyped RAG metadata; reindex is required."
        )
    try:
        identity = FrozenIndexIdentity(
            index_name=index_name,
            index_uuid=str(index_settings["uuid"]),
            index_build_id=UUID(rag["index_build_id"]),
            projection_id=UUID(rag["projection_id"]),
            indexing_profile_id=UUID(rag["indexing_profile_id"]),
            vector_dimension=rag["vector_dimension"],
            mapping_version=rag["mapping_version"],
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise FrozenIndexReindexRequiredError(
            "The physical index has invalid index.meta.rag fields; reindex is required."
        ) from exc
    if (
        str(identity.index_build_id) != rag["index_build_id"]
        or str(identity.projection_id) != rag["projection_id"]
        or str(identity.indexing_profile_id) != rag["indexing_profile_id"]
    ):
        raise FrozenIndexReindexRequiredError(
            "The physical index RAG descriptor is not canonical; reindex is required."
        )
    return FrozenIndexDescription(identity)


def _require_same_frozen_identity(
    expected: FrozenIndexIdentity,
    actual: FrozenIndexIdentity,
) -> None:
    if actual != expected:
        difference = "UUID" if actual.index_uuid != expected.index_uuid else "descriptor"
        raise FrozenIndexDriftError(
            f"The frozen Elasticsearch index {difference} no longer matches the run snapshot."
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
            if isinstance(index_alias, FrozenIndexTarget):
                responses = [
                    await _search_frozen(
                        self.client,
                        identity,
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
                                "filter": [
                                    *build_scope_filter(actor_id, scope),
                                    *_identity_filters(identity),
                                ],
                            }
                        },
                        size=top_k,
                    )
                    for identity in index_alias.identities
                ]
            else:
                responses = [
                    cast(
                        dict[str, Any],
                        await self.client.search(
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
                        ),
                    )
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
            if isinstance(index_alias, FrozenIndexTarget):
                responses = [
                    await _search_frozen(
                        self.client,
                        identity,
                        knn={
                            "field": "embedding",
                            "query_vector": list(query_vector),
                            "k": top_k,
                            "num_candidates": top_k,
                            "filter": {
                                "bool": {
                                    "filter": [
                                        *build_scope_filter(actor_id, scope),
                                        *_identity_filters(identity),
                                    ]
                                }
                            },
                        },
                        size=top_k,
                    )
                    for identity in index_alias.identities
                ]
            else:
                responses = [
                    cast(
                        dict[str, Any],
                        await self.client.search(
                            index=index_alias.name,
                            knn={
                                "field": "embedding",
                                "query_vector": list(query_vector),
                                "k": top_k,
                                "num_candidates": top_k,
                                "filter": {
                                    "bool": {
                                        "filter": build_scope_filter(actor_id, scope)
                                    }
                                },
                            },
                            size=top_k,
                            source={"includes": list(RETRIEVAL_SOURCE_FIELDS)},
                        ),
                    )
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


def _identity_filters(identity: FrozenIndexIdentity) -> list[dict[str, object]]:
    return [
        {"term": {"index_build_id": str(identity.index_build_id)}},
        {"term": {"projection_id": str(identity.projection_id)}},
        {"term": {"indexing_profile_id": str(identity.indexing_profile_id)}},
        {"term": {"rag_mapping_version": identity.mapping_version}},
    ]


async def _search_frozen(
    client: AsyncElasticsearch,
    identity: FrozenIndexIdentity,
    *,
    size: int,
    query: dict[str, object] | None = None,
    knn: dict[str, object] | None = None,
) -> dict[str, Any]:
    before = await describe_frozen_index(client, identity.index_name)
    _require_same_frozen_identity(identity, before.identity)
    pit_id: str | None = None
    primary_error: BaseException | None = None
    try:
        opened = cast(
            dict[str, Any],
            await client.open_point_in_time(index=identity.index_name, keep_alive="1m"),
        )
        pit_id = str(opened["id"])
        after = await describe_frozen_index(client, identity.index_name)
        _require_same_frozen_identity(identity, after.identity)
        if query is not None:
            response = cast(
                dict[str, Any],
                await client.search(
                    pit={"id": pit_id, "keep_alive": "1m"},
                    query=cast(Any, query),
                    size=size,
                    source={"includes": list(RETRIEVAL_SOURCE_FIELDS)},
                ),
            )
        else:
            if knn is None:
                raise TypeError("A frozen Elasticsearch search requires query or kNN input.")
            response = cast(
                dict[str, Any],
                await client.search(
                    pit={"id": pit_id, "keep_alive": "1m"},
                    knn=cast(Any, knn),
                    size=size,
                    source={"includes": list(RETRIEVAL_SOURCE_FIELDS)},
                ),
            )
        response_pit_id = response.get("pit_id")
        if isinstance(response_pit_id, str) and response_pit_id:
            pit_id = response_pit_id
        for hit in _raw_hits(response):
            _validate_frozen_hit(hit, identity)
        return response
    except BaseException as exc:
        primary_error = exc
        raise
    finally:
        if pit_id is not None:
            try:
                closed = cast(
                    dict[str, Any], await client.close_point_in_time(id=pit_id)
                )
                if not bool(closed.get("succeeded", False)):
                    raise PointInTimeCleanupError(
                        "Elasticsearch point-in-time cleanup was not acknowledged for "
                        f"{identity.index_name}."
                    )
            except Exception as exc:
                cleanup_error = (
                    exc
                    if isinstance(exc, PointInTimeCleanupError)
                    else PointInTimeCleanupError(
                        f"Elasticsearch point-in-time cleanup failed for {identity.index_name}."
                    )
                )
                if primary_error is None:
                    raise cleanup_error from exc
                cast(Any, primary_error).pit_cleanup_error = cleanup_error
                primary_error.add_note(str(cleanup_error))
                logger.error(
                    "Evaluation point-in-time cleanup failed after a primary search error.",
                    exc_info=exc,
                )


def _validate_frozen_hit(
    hit: dict[str, Any],
    identity: FrozenIndexIdentity,
) -> None:
    source = cast(dict[str, Any], hit.get("_source", {}))
    if (
        str(source.get("index_build_id")) != str(identity.index_build_id)
        or str(source.get("projection_id")) != str(identity.projection_id)
        or str(source.get("indexing_profile_id")) != str(identity.indexing_profile_id)
        or source.get("rag_mapping_version") != identity.mapping_version
    ):
        raise FrozenIndexDriftError(
            "A retrieved document does not match the frozen build/projection/profile descriptor."
        )


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
