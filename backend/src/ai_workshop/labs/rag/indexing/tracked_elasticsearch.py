"""Owner-only ES provenance checks. No helper retries or raw backend error payloads."""

import asyncio
import hashlib
import json
import math
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from elastic_transport import ObjectApiResponse
from elasticsearch import AsyncElasticsearch, NotFoundError

from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, IndexDocument
from ai_workshop.labs.rag.indexing.elasticsearch import build_mapping
from ai_workshop.labs.rag.indexing.tracking_contracts import (
    IndexBinding,
    IndexResource,
    IndexTrackingError,
    index_chunk_ids_fingerprint,
)

_IDENTITY = "rag_index_identity_conflict"
_INPUT = "rag_index_input_conflict"
_OBSERVATION = "rag_index_observation_failed"
_UNCONFIRMED = "rag_index_writer_unconfirmed"
_PAGE_SIZE = 500


class IndexPreparationFailed(IndexTrackingError):
    """Safe prepare failure with explicit evidence about submitted writes."""

    def __init__(self, code: str, *, writer_confirmed_ended: bool) -> None:
        super().__init__(code)
        self.writer_confirmed_ended = writer_confirmed_ended


@dataclass(frozen=True, slots=True)
class TrackedIndexObservation:
    exists: bool
    index_uuid: str | None
    chunk_count: int
    aliases: tuple[str, ...]


def index_input_fingerprint(documents: Sequence[IndexDocument]) -> str:
    """Hash all transmitted fields, sorted by immutable chunk ID (JSON v1)."""
    if len({document.chunk_id for document in documents}) != len(documents):
        raise IndexTrackingError(_INPUT)
    try:
        payload = {
            "version": 1,
            "documents": [
                document.to_projection()
                for document in sorted(documents, key=lambda document: document.chunk_id)
            ],
        }
        canonical = json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
    except (ValueError, TypeError, UnicodeError):
        raise IndexTrackingError(_INPUT) from None
    return hashlib.sha256(canonical).hexdigest()


def _mapping(resource: IndexResource) -> dict[str, Any]:
    descriptor = IndexDescriptor(
        resource.vector_dimension,
        resource.similarity,
        resource.index_name,
        resource.indexing_profile_id,
        resource.build_id,
        resource.projection_id,
        resource.mapping_version,
    )
    mapping: dict[str, Any] = build_mapping(descriptor)["mappings"]
    mapping["_meta"]["rag_index_resource"] = {
        "contract_version": 1,
        "resource_id": str(resource.build_id),
        "job_id": str(resource.job_id),
        "workspace_id": str(resource.workspace_id),
        "document_id": str(resource.document_id),
        "asset_version_id": str(resource.asset_version_id),
        "document_processing_profile_id": str(resource.document_processing_profile_id),
        "input_fingerprint": resource.input_fingerprint,
        "chunk_ids_sha256": resource.chunk_ids_sha256,
    }
    return mapping


def _contains(actual: Any, expected: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(actual, Mapping) and all(
            key in actual and _contains(actual[key], value) for key, value in expected.items()
        )
    return actual == expected and type(actual) is type(expected)


def _shards(response: Mapping[str, Any] | ObjectApiResponse[Any]) -> None:
    shards = response.get("_shards", {})
    total, successful = shards.get("total"), shards.get("successful")
    if (
        type(total) is not int
        or total < 1
        or successful != total
        or shards.get("failed") != 0
        or response.get("timed_out", False)
        or response.get("terminated_early", False)
    ):
        raise IndexTrackingError(_OBSERVATION)


def _ownership(resource: IndexResource) -> dict[str, object]:
    return {
        "projection_id": str(resource.projection_id),
        "asset_version_id": str(resource.asset_version_id),
        "workspace_id": str(resource.workspace_id),
        "index_build_id": str(resource.build_id),
        "indexing_profile_id": str(resource.indexing_profile_id),
        "rag_mapping_version": resource.mapping_version,
    }


def _refresh_shards(response: Mapping[str, Any] | ObjectApiResponse[Any]) -> None:
    # Refresh totals include unassigned replicas. Count/search below must still
    # report complete logical-shard coverage before any successful observation.
    shards = response.get("_shards", {})
    total, successful = shards.get("total"), shards.get("successful")
    if (
        type(total) is not int
        or type(successful) is not int
        or not 1 <= successful <= total
        or shards.get("failed") != 0
    ):
        raise IndexTrackingError(_OBSERVATION)


class TrackedElasticsearchIndex:
    def __init__(self, client: AsyncElasticsearch, binding: IndexBinding) -> None:
        self.client = client.options(max_retries=0, retry_on_timeout=False, retry_on_status=())
        self.binding = binding

    async def prepare(
        self,
        resource: IndexResource,
        documents: Sequence[IndexDocument],
        on_identity: Callable[[str], Awaitable[None]],
    ) -> TrackedIndexObservation:
        mutation_started = False
        writer_confirmed_ended = True
        try:
            expected = self._inputs(resource, [document.chunk_id for document in documents])
            if resource.input_fingerprint != index_input_fingerprint(documents):
                raise IndexTrackingError(_INPUT)
            for document in documents:
                if (
                    not _contains(document.to_projection(), _ownership(resource))
                    or document.embedding is None
                    or len(document.embedding) != resource.vector_dimension
                    or any(not math.isfinite(value) for value in document.embedding)
                ):
                    raise IndexTrackingError(_INPUT)
            identity = await self._identity(resource)
            if identity is None:
                if resource.index_uuid is not None:
                    raise IndexTrackingError(_IDENTITY)
                mutation_started = True
                writer_confirmed_ended = False
                response = await self.client.indices.create(
                    index=resource.index_name, mappings=_mapping(resource)
                )
                if response.get("acknowledged") is not True:
                    raise IndexTrackingError(_UNCONFIRMED)
                writer_confirmed_ended = True
                identity = await self._identity(resource)
                if identity is None:
                    raise IndexTrackingError(_OBSERVATION)
            else:
                # Previously acknowledged partial writes need not yet be search-visible.
                _refresh_shards(await self.client.indices.refresh(index=resource.index_name))
                await self._records(resource, expected, exact=False)
            # The callback must commit the UUID before any bulk request is submitted.
            try:
                await on_identity(identity.index_uuid or "")
            except (Exception, asyncio.CancelledError):
                writer_confirmed_ended = False
                raise IndexTrackingError(_UNCONFIRMED) from None
            if documents:
                operations: list[dict[str, Any]] = []
                for document in documents:
                    operations.extend(
                        [
                            {
                                "index": {
                                    "_index": resource.index_name,
                                    "_id": str(document.chunk_id),
                                }
                            },
                            document.to_projection(),
                        ]
                    )
                mutation_started = True
                writer_confirmed_ended = False
                response = await self.client.bulk(
                    operations=operations, refresh=False, include_source_on_error=False
                )
                items = response.get("items")
                if not isinstance(items, list) or len(items) != len(documents):
                    raise IndexTrackingError(_UNCONFIRMED)
                if any(not isinstance(item.get("index", {}).get("status"), int) for item in items):
                    raise IndexTrackingError(_UNCONFIRMED)
                writer_confirmed_ended = True
                if response.get("errors") is not False:
                    raise IndexTrackingError(_OBSERVATION)
                for document, item in zip(documents, items, strict=True):
                    result = item.get("index", {})
                    if (
                        result.get("status") not in (200, 201)
                        or "error" in result
                        or result.get("_id") != str(document.chunk_id)
                        or result.get("_index") != resource.index_name
                    ):
                        raise IndexTrackingError(_OBSERVATION)
            _refresh_shards(await self.client.indices.refresh(index=resource.index_name))
            count = await self._records(resource, expected, exact=True)
            final = await self._identity(resource)
            if final is None or final.index_uuid != identity.index_uuid:
                raise IndexTrackingError(_IDENTITY)
            return TrackedIndexObservation(True, final.index_uuid, count, final.aliases)
        except IndexTrackingError as error:
            raise IndexPreparationFailed(
                error.code, writer_confirmed_ended=writer_confirmed_ended
            ) from None
        except (Exception, asyncio.CancelledError):
            raise IndexPreparationFailed(
                _UNCONFIRMED if mutation_started else _OBSERVATION, writer_confirmed_ended=False
            ) from None

    async def observe(
        self, resource: IndexResource, expected_chunk_ids: Sequence[UUID]
    ) -> TrackedIndexObservation:
        try:
            if resource.binding != self.binding:
                raise IndexTrackingError("rag_index_binding_mismatch")
            identity = await self._identity(resource)
            if identity is None:
                return TrackedIndexObservation(False, None, 0, ())
            expected = self._inputs(resource, expected_chunk_ids)
            count = await self._records(resource, expected, exact=True)
            final = await self._identity(resource)
            if final is None or final != identity:
                raise IndexTrackingError(_IDENTITY)
            return TrackedIndexObservation(True, final.index_uuid, count, final.aliases)
        except IndexTrackingError:
            raise
        except (Exception, asyncio.CancelledError):
            raise IndexTrackingError(_OBSERVATION) from None

    def _inputs(self, resource: IndexResource, ids: Sequence[UUID]) -> set[str]:
        if resource.binding != self.binding:
            raise IndexTrackingError("rag_index_binding_mismatch")
        if (
            resource.input_fingerprint is None
            or resource.chunk_ids_sha256 is None
            or index_chunk_ids_fingerprint(ids) != resource.chunk_ids_sha256
        ):
            raise IndexTrackingError(_INPUT)
        return {str(value) for value in ids}

    async def _identity(self, resource: IndexResource) -> TrackedIndexObservation | None:
        if (await self.client.info()).get("cluster_uuid") != self.binding.cluster_uuid:
            raise IndexTrackingError("rag_index_binding_mismatch")
        try:
            resolved = await self.client.indices.resolve_index(
                name=resource.index_name,
                expand_wildcards="all",
                allow_no_indices=True,
                ignore_unavailable=False,
            )
        except NotFoundError:
            return None
        indices = resolved.get("indices")
        if resolved.get("aliases") or resolved.get("data_streams"):
            raise IndexTrackingError(_IDENTITY)
        if indices == []:
            return None
        if (
            not isinstance(indices, list)
            or len(indices) != 1
            or indices[0].get("name") != resource.index_name
            or indices[0].get("data_stream") is not None
            or "closed" in indices[0].get("attributes", [])
        ):
            raise IndexTrackingError(_IDENTITY)
        response = await self.client.indices.get(
            index=resource.index_name,
            expand_wildcards="none",
            allow_no_indices=False,
            ignore_unavailable=False,
        )
        if set(response) != {resource.index_name}:
            raise IndexTrackingError(_IDENTITY)
        actual = response[resource.index_name]
        index_uuid = actual.get("settings", {}).get("index", {}).get("uuid")
        mapping = actual.get("mappings", {})
        expected = _mapping(resource)
        if (
            not isinstance(index_uuid, str)
            or not index_uuid
            or resource.index_uuid is not None
            and resource.index_uuid != index_uuid
            or mapping.get("_meta") != expected["_meta"]
            or mapping.get("_source", {}).get("enabled", True) is not True
            or not _contains(mapping, expected)
        ):
            raise IndexTrackingError(_IDENTITY)
        aliases = actual.get("aliases")
        if not isinstance(aliases, dict) or any(not isinstance(key, str) for key in aliases):
            raise IndexTrackingError(_OBSERVATION)
        return TrackedIndexObservation(True, index_uuid, 0, tuple(sorted(aliases)))

    async def _records(self, resource: IndexResource, expected: set[str], *, exact: bool) -> int:
        count_response = await self.client.count(index=resource.index_name, query={"match_all": {}})
        _shards(count_response)
        total = count_response.get("count")
        if type(total) is not int or total < 0:
            raise IndexTrackingError(_OBSERVATION)
        if total > len(expected) or exact and total != len(expected):
            raise IndexTrackingError(_IDENTITY)
        seen: set[str] = set()
        after: list[Any] | None = None
        while True:
            response = await self.client.search(
                index=resource.index_name,
                query={"match_all": {}},
                size=_PAGE_SIZE,
                sort=[{"chunk_id": "asc"}],
                search_after=after,
                track_total_hits=True,
                allow_partial_search_results=False,
                source_includes=["chunk_id", *_ownership(resource)],
            )
            _shards(response)
            hits_info = response.get("hits", {})
            if hits_info.get("total") != {"value": total, "relation": "eq"}:
                raise IndexTrackingError(_OBSERVATION)
            hits = hits_info.get("hits")
            if not isinstance(hits, list):
                raise IndexTrackingError(_OBSERVATION)
            if not hits:
                break
            for hit in hits:
                source = hit.get("_source", {})
                chunk = source.get("chunk_id")
                if (
                    not isinstance(chunk, str)
                    or chunk not in expected
                    or chunk in seen
                    or hit.get("_id") != chunk
                    or hit.get("_index") != resource.index_name
                    or not _contains(source, _ownership(resource))
                ):
                    raise IndexTrackingError(_IDENTITY)
                seen.add(chunk)
            next_after = hits[-1].get("sort")
            if next_after != [hits[-1]["_source"]["chunk_id"]] or next_after == after:
                raise IndexTrackingError(_OBSERVATION)
            after = next_after
            if len(seen) > total:
                raise IndexTrackingError(_OBSERVATION)
        if len(seen) != total or exact and seen != expected:
            raise IndexTrackingError(_IDENTITY)
        return total
