"""Pure opaque metadata/Lucene-cardinality decoding, never source authority.

These inputs establish neither an atomic snapshot nor unchanged document bodies.
The producer separately proves capture origin, complete classification, writer
quiescence and the constrained original-volume transition. No index-read rights
or requests are supplied by this module.
"""

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from ai_workshop.labs.rag.indexing.access_epoch_index_inventory import (
    _canonical,
    _decimal,
    _identifier,
    _integer,
    _load,
    _name,
    _object,
    _settings_projection,
)

_DENIED = "foreign_inventory_decode_denied"
_MISMATCH = "foreign_inventory_preservation_mismatch"
_MAX_INDICES = 1024
_ROUTE_KEYS = {"primary", "state", "node", "relocating_node", "shard", "index"}
_OPTIONAL_ROUTE_KEYS = {
    "allocation_id",
    "relocation_failure_info",
    "recovery_source",
    "unassigned_info",
}


@dataclass(frozen=True, slots=True)
class OpaqueIndexObservation:
    uuid: str
    schema: Literal["opaque_non_rag_v1"]
    count_kind: Literal["lucene_live_docs"]
    count: int
    settings_sha256: str
    cardinality_sha256: str


@dataclass(frozen=True, slots=True)
class DecodedForeignIndex:
    name: str = field(repr=False)
    observation: OpaqueIndexObservation
    private_metadata: bytes = field(repr=False)
    deleted_docs: int = field(repr=False, compare=False)


@dataclass(frozen=True, slots=True)
class DecodedForeignInventory:
    cluster_uuid: str
    cluster_name: str
    stable_node_id: str
    entries: tuple[DecodedForeignIndex, ...]
    # Bracketing/restart association is a separate producer responsibility.
    # Retain every parsed physical name/UUID privately, without any exemption.
    private_physical_inventory: bytes = field(repr=False)


def _cluster_name(value: object) -> str:
    if type(value) is not str or not 1 <= len(value) <= 255 or any(ord(c) < 32 for c in value):
        raise ValueError(_DENIED)
    return value


def _routing(name: str, routes: object, settings: dict[str, Any], stable_node_id: str) -> None:
    entry = _object(routes)
    if set(entry) != {"shards"}:
        raise ValueError(_DENIED)
    shards = _object(entry["shards"])
    expected_shards = _decimal(settings.get("index.number_of_shards"), 1, 1024)
    replicas = _decimal(settings.get("index.number_of_replicas"), 0, 1024)
    # The pinned singleton 0-1 policy is checked against actual primary-only
    # routing, not a guessed replica count derived from the number of nodes.
    auto_expand = settings.get("index.auto_expand_replicas", "false")
    if auto_expand not in {"false", "0-1"} or auto_expand == "0-1" and replicas != 0:
        raise ValueError(_DENIED)
    if set(shards) != {str(number) for number in range(expected_shards)}:
        raise ValueError(_DENIED)
    for number, copies in shards.items():
        if type(copies) is not list or len(copies) != 1 + replicas:
            raise ValueError(_DENIED)
        primary_count = 0
        for item in copies:
            route = _object(item)
            if not _ROUTE_KEYS <= set(route) <= _ROUTE_KEYS | _OPTIONAL_ROUTE_KEYS:
                raise ValueError(_DENIED)
            if "allocation_id" in route:
                allocation = _object(route["allocation_id"])
                if set(allocation) != {"id"}:
                    raise ValueError(_DENIED)
                _identifier(allocation["id"])
            if "relocation_failure_info" in route:
                failure = _object(route["relocation_failure_info"])
                if set(failure) != {"failed_attempts"}:
                    raise ValueError(_DENIED)
                _integer(failure["failed_attempts"])
            if "recovery_source" in route or "unassigned_info" in route:
                if route["primary"] is not False or route["state"] != "UNASSIGNED":
                    raise ValueError(_DENIED)
                source = _object(route.get("recovery_source"))
                unassigned = _object(route.get("unassigned_info"))
                if (
                    source != {"type": "PEER"}
                    or set(unassigned) != {"reason", "at", "delayed", "allocation_status"}
                    or type(unassigned["delayed"]) is not bool
                    or type(unassigned["at"]) is not str
                    or not 1 <= len(unassigned["at"]) <= 64
                    or datetime.fromisoformat(unassigned["at"]).utcoffset() != timedelta(0)
                ):
                    raise ValueError(_DENIED)
                _identifier(unassigned["reason"])
                _identifier(unassigned["allocation_status"])
            if (
                type(route["primary"]) is not bool
                or _integer(route["shard"], 0, 1023) != int(number)
                or type(route["index"]) is not str
                or route["index"] != name
                or route["relocating_node"] is not None
            ):
                raise ValueError(_DENIED)
            if route["primary"]:
                primary_count += 1
                if route["state"] != "STARTED" or _identifier(route["node"]) != stable_node_id:
                    raise ValueError(_DENIED)
            elif route["state"] != "UNASSIGNED" or route["node"] is not None:
                raise ValueError(_DENIED)
        if primary_count != 1:
            raise ValueError(_DENIED)


def _metadata(value: object, *, selected: bool) -> tuple[dict[str, Any], bytes]:
    metadata = _object(value)
    if set(metadata) not in (
        {"state", "settings", "mappings", "aliases"},
        {"state", "settings", "mappings", "aliases", "system"},
    ):
        raise ValueError(_DENIED)
    if "system" in metadata and (
        type(metadata["system"]) is not bool or selected and metadata["system"] is not False
    ):
        raise ValueError(_DENIED)
    if metadata["state"] != "open":
        raise ValueError(_DENIED)
    settings = _object(metadata["settings"])
    _object(metadata["mappings"])
    aliases = metadata["aliases"]
    # The pinned names-only representation can establish absence only. Any
    # nonempty name list cannot establish preservation of the alias definitions.
    if type(aliases) is list:
        if selected and aliases:
            raise ValueError(_DENIED)
        names = [_name(alias) for alias in aliases]
        if len(names) != len(set(names)):
            raise ValueError(_DENIED)
    else:
        _object(aliases)
    return settings, _settings_projection(settings, {})


def _docs(value: object) -> tuple[int, int]:
    row = _object(value)
    if set(row) != {"docs"}:
        raise ValueError(_DENIED)
    docs = _object(row["docs"])
    if set(docs) not in ({"count", "deleted"}, {"count", "deleted", "total_size_in_bytes"}):
        raise ValueError(_DENIED)
    if "total_size_in_bytes" in docs:
        _integer(docs["total_size_in_bytes"])
    return _integer(docs["count"]), _integer(docs["deleted"])


def _no_rag_metadata(mappings: object) -> None:
    mapping = _object(mappings)
    candidates = [mapping]
    if "_doc" in mapping:
        candidates.append(_object(mapping["_doc"]))
    for candidate in candidates:
        if "_meta" in candidate:
            meta = _object(candidate["_meta"])
            if "rag" in meta or "rag_index_resource" in meta:
                raise ValueError(_DENIED)


def decode_foreign_inventory(
    state_raw: bytes,
    stats_raw: bytes,
    *,
    cluster_uuid: str,
    cluster_name: str,
    stable_node_id: str,
    foreign_names: tuple[str, ...],
) -> DecodedForeignInventory:
    """Join all supplied physical rows before selecting typed opaque entries.

    Expected identity/name arguments are structural constraints, not trusted
    producer capabilities. The caller must not promote these DTOs to proof.
    """
    try:
        return _decode(
            state_raw, stats_raw, cluster_uuid, cluster_name, stable_node_id, foreign_names
        )
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise ValueError(_DENIED) from None


def _decode(
    state_raw: bytes,
    stats_raw: bytes,
    cluster_uuid: str,
    cluster_name: str,
    stable_node_id: str,
    foreign_names: tuple[str, ...],
) -> DecodedForeignInventory:
    _identifier(cluster_uuid)
    _cluster_name(cluster_name)
    _identifier(stable_node_id)
    if (
        type(foreign_names) is not tuple
        or len(foreign_names) > _MAX_INDICES
        or any(type(name) is not str for name in foreign_names)
        or foreign_names != tuple(sorted(set(foreign_names)))
    ):
        raise ValueError(_DENIED)
    state, stats = _load(state_raw), _load(stats_raw)
    if set(state) != {"cluster_name", "cluster_uuid", "metadata", "routing_table"}:
        raise ValueError(_DENIED)
    if (
        _cluster_name(state["cluster_name"]) != cluster_name
        or _identifier(state["cluster_uuid"]) != cluster_uuid
    ):
        raise ValueError(_DENIED)
    if (
        set(stats) != {"cluster_name", "_nodes", "nodes"}
        or _cluster_name(stats["cluster_name"]) != cluster_name
    ):
        raise ValueError(_DENIED)
    node_counts = _object(stats["_nodes"])
    if set(node_counts) != {"total", "successful", "failed"} or any(
        _integer(node_counts[key]) != expected
        for key, expected in (("total", 1), ("successful", 1), ("failed", 0))
    ):
        raise ValueError(_DENIED)
    nodes = _object(stats["nodes"])
    if set(nodes) != {stable_node_id}:
        raise ValueError(_DENIED)
    node = _object(nodes[stable_node_id])
    if set(node) != {"indices"}:
        raise ValueError(_DENIED)
    node_indices = _object(node["indices"])
    metadata = _object(state["metadata"])
    routing = _object(state["routing_table"])
    if any(set(value) != {"indices"} for value in (node_indices, metadata, routing)):
        raise ValueError(_DENIED)
    indices = _object(metadata["indices"])
    routes = _object(routing["indices"])
    counts = _object(node_indices["indices"])
    if (
        len(indices) > _MAX_INDICES
        or set(indices) != set(routes)
        or set(indices) != set(counts)
        or not set(foreign_names) <= set(indices)
    ):
        raise ValueError(_DENIED)
    physical: dict[str, str] = {}
    entries: list[DecodedForeignIndex] = []
    for name, value in sorted(indices.items()):
        _name(name)
        settings, public_settings = _metadata(value, selected=name in foreign_names)
        uuid = _identifier(settings["index.uuid"])
        if uuid in physical.values():
            raise ValueError(_DENIED)
        physical[name] = uuid
        _routing(name, routes[name], settings, stable_node_id)
        count, deleted = _docs(counts[name])
        if name not in foreign_names:
            continue
        _no_rag_metadata(value["mappings"])
        public_cardinality = {
            "schema": "opaque_non_rag_v1",
            "count_kind": "lucene_live_docs",
            "uuid": uuid,
            "count": count,
        }
        observation = OpaqueIndexObservation(
            uuid=uuid,
            schema="opaque_non_rag_v1",
            count_kind="lucene_live_docs",
            count=count,
            settings_sha256=hashlib.sha256(public_settings).hexdigest(),
            cardinality_sha256=hashlib.sha256(_canonical(public_cardinality)).hexdigest(),
        )
        entries.append(DecodedForeignIndex(name, observation, _canonical(value), deleted))
    return DecodedForeignInventory(
        cluster_uuid, cluster_name, stable_node_id, tuple(entries), _canonical(physical)
    )


def require_same_private_foreign_inventory(
    before: DecodedForeignInventory, after: DecodedForeignInventory
) -> None:
    """Metadata/live-cardinality equality, never a document-body equality claim."""
    if type(before) is not DecodedForeignInventory or type(after) is not DecodedForeignInventory:
        raise ValueError(_MISMATCH)
    for value in (before, after):
        for entry in value.entries:
            if (
                type(entry) is not DecodedForeignIndex
                or type(entry.observation) is not OpaqueIndexObservation
                or entry.observation.count_kind != "lucene_live_docs"
                or entry.observation.schema != "opaque_non_rag_v1"
            ):
                raise ValueError(_MISMATCH)
    if before != after:
        raise ValueError(_MISMATCH)
