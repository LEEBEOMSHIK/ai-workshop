"""Pure complete joins for unmanaged legacy preservation; never source authority.

Global metadata/NodeStats provide sampled metadata and Lucene live cardinality,
not document body equality. The native producer must bind the exact exclusion
issuer and captures. Whole-map O/B/F transition verification remains separate.
"""

from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from ai_workshop.labs.rag.indexing.access_epoch_foreign_inventory import (
    _cluster_name,
    _docs,
    _routing,
)
from ai_workshop.labs.rag.indexing.access_epoch_index_inventory import (
    _canonical,
    _identifier,
    _integer,
    _load,
    _name,
    _object,
    decode_index_metadata,
)
from ai_workshop.labs.rag.indexing.access_epoch_namespace_source import (
    OriginalUnmanagedPhysicalEntry,
)
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor

_DENIED = "unmanaged_inventory_decode_denied"
_MISMATCH = "unmanaged_inventory_preservation_mismatch"


@dataclass(frozen=True, slots=True)
class DecodedUnmanagedLegacyIndex:
    name: str = field(repr=False)
    uuid: str
    indexing_profile_id: UUID
    index_build_id: UUID
    prefix: str
    reason: Literal["outside_configured_prefix", "missing_indexing_profile"]
    count: int
    private_metadata: bytes = field(repr=False)
    deleted_docs: int = field(repr=False, compare=False)
    schema: Literal["unmanaged_legacy_rag_v1"] = "unmanaged_legacy_rag_v1"
    count_kind: Literal["lucene_live_docs"] = "lucene_live_docs"


@dataclass(frozen=True, slots=True)
class DecodedUnmanagedLegacyInventory:
    cluster_uuid: str
    cluster_name: str
    stable_node_id: str
    entries: tuple[DecodedUnmanagedLegacyIndex, ...]
    private_physical_inventory: bytes = field(repr=False)


def decode_unmanaged_inventory(
    state_raw: bytes,
    stats_raw: bytes,
    *,
    cluster_uuid: str,
    cluster_name: str,
    stable_node_id: str,
    unmanaged_entries: tuple[OriginalUnmanagedPhysicalEntry, ...],
) -> DecodedUnmanagedLegacyInventory:
    try:
        return _decode(
            state_raw, stats_raw, cluster_uuid, cluster_name, stable_node_id, unmanaged_entries
        )
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise ValueError(_DENIED) from None


def _decode(
    state_raw: bytes,
    stats_raw: bytes,
    cluster_uuid: str,
    cluster_name: str,
    stable_node_id: str,
    unmanaged_entries: tuple[OriginalUnmanagedPhysicalEntry, ...],
) -> DecodedUnmanagedLegacyInventory:
    _identifier(cluster_uuid)
    _cluster_name(cluster_name)
    _identifier(stable_node_id)
    if (
        type(unmanaged_entries) is not tuple
        or len(unmanaged_entries) > 64
        or any(type(e) is not OriginalUnmanagedPhysicalEntry for e in unmanaged_entries)
    ):
        raise ValueError(_DENIED)
    selected = {e.name: e for e in unmanaged_entries}
    if len(selected) != len(unmanaged_entries) or tuple(selected) != tuple(sorted(selected)):
        raise ValueError(_DENIED)
    state, stats = _load(state_raw), _load(stats_raw)
    if (
        set(state) != {"cluster_name", "cluster_uuid", "metadata", "routing_table"}
        or state["cluster_uuid"] != cluster_uuid
        or state["cluster_name"] != cluster_name
        or set(stats) != {"cluster_name", "_nodes", "nodes"}
        or stats["cluster_name"] != cluster_name
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
    metadata, routing, node_indices = (
        _object(state["metadata"]),
        _object(state["routing_table"]),
        _object(node["indices"]),
    )
    if any(set(value) != {"indices"} for value in (metadata, routing, node_indices)):
        raise ValueError(_DENIED)
    indices, routes, counts = (
        _object(metadata["indices"]),
        _object(routing["indices"]),
        _object(node_indices["indices"]),
    )
    if (
        len(indices) > 1024
        or set(indices) != set(routes)
        or set(indices) != set(counts)
        or not set(selected) <= set(indices)
    ):
        raise ValueError(_DENIED)
    physical: dict[str, str] = {}
    decoded: list[DecodedUnmanagedLegacyIndex] = []
    for name, value in sorted(indices.items()):
        _name(name)
        row = _object(value)
        if (
            set(row) != {"state", "settings", "mappings", "aliases", "system"}
            or row["state"] != "open"
            or type(row["system"]) is not bool
        ):
            raise ValueError(_DENIED)
        settings = _object(row["settings"])
        _object(row["mappings"])
        aliases = row["aliases"]
        if type(aliases) is list:
            names = [_name(a) for a in aliases]
            if len(set(names)) != len(names):
                raise ValueError(_DENIED)
        else:
            _object(aliases)
        uuid = _identifier(settings["index.uuid"])
        if uuid in physical.values():
            raise ValueError(_DENIED)
        physical[name] = uuid
        _routing(name, routes[name], settings, stable_node_id)
        count, deleted = _docs(counts[name])
        if name not in selected:
            continue
        entry = selected[name]
        if (
            type(entry.reason) is not str
            or entry.reason not in {"outside_configured_prefix", "missing_indexing_profile"}
            or type(entry.indexing_profile_id) is not UUID
            or type(entry.index_build_id) is not UUID
            or type(entry.private_metadata) is not bytes
            or type(entry.aliases) is not tuple
            or type(aliases) is not list
            or tuple(aliases) != entry.aliases
            or uuid != entry.uuid
            or row["system"] is not False
            or settings.get("index.hidden", "false") != "false"
            or _canonical({name: row}) != entry.private_metadata
        ):
            raise ValueError(_DENIED)
        permissions = AccessEpochPermissions(entry.prefix, ((entry.indexing_profile_id, None),))
        if name != IndexDescriptor(1, "cosine").concrete_index_name(
            entry.prefix, entry.indexing_profile_id, entry.index_build_id
        ):
            raise ValueError(_DENIED)
        mapping = _object(row["mappings"])
        if "_doc" in mapping:
            if set(mapping) != {"_doc"}:
                raise ValueError(_DENIED)
            mapping = _object(mapping["_doc"])
        if "rag_index_resource" in _object(mapping.get("_meta")):
            raise ValueError(_DENIED)
        legacy = decode_index_metadata(
            name,
            permissions,
            _canonical(
                {
                    name: {
                        "aliases": {a: {} for a in aliases},
                        "settings": settings,
                        "mappings": mapping,
                        "defaults": {},
                    }
                }
            ),
        )
        if legacy.schema != "legacy_rag_v1":
            raise ValueError(_DENIED)
        decoded.append(
            DecodedUnmanagedLegacyIndex(
                name,
                uuid,
                entry.indexing_profile_id,
                entry.index_build_id,
                entry.prefix,
                entry.reason,
                count,
                entry.private_metadata,
                deleted,
            )
        )
    return DecodedUnmanagedLegacyInventory(
        cluster_uuid, cluster_name, stable_node_id, tuple(decoded), _canonical(physical)
    )


def require_same_unmanaged_entries(
    before: DecodedUnmanagedLegacyInventory,
    after: DecodedUnmanagedLegacyInventory,
) -> None:
    """Preserve selected entries only; no whole-map/creation authority is implied."""
    if (
        type(before) is not DecodedUnmanagedLegacyInventory
        or type(after) is not DecodedUnmanagedLegacyInventory
        or (before.cluster_uuid, before.cluster_name, before.stable_node_id, before.entries)
        != (after.cluster_uuid, after.cluster_name, after.stable_node_id, after.entries)
    ):
        raise ValueError(_MISMATCH)
