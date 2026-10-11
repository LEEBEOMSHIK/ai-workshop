"""Pure source-contract main security decoding; no creation or source authority."""

from dataclasses import dataclass, field, fields

from ai_workshop.labs.rag.indexing.access_epoch_foreign_inventory import _docs
from ai_workshop.labs.rag.indexing.access_epoch_index_inventory import (
    _canonical,
    _identifier,
    _load,
    _object,
)
from ai_workshop.labs.rag.indexing.access_epoch_native import ORIGINAL_IMAGE, OriginalImageReference
from ai_workshop.labs.rag.indexing.access_epoch_security_descriptor_source import (
    ObservedSecurityDescriptor,
)
from ai_workshop.labs.rag.indexing.access_epoch_unmanaged_inventory import (
    decode_unmanaged_inventory,
)

_DENIED = "security_inventory_decode_denied"


@dataclass(frozen=True, slots=True)
class DecodedMainSecurityIndex:
    name: str
    uuid: str
    count: int
    private_metadata: bytes = field(repr=False)
    private_physical_inventory: bytes = field(repr=False)
    deleted_docs: int = field(repr=False, compare=False)
    schema: str = "main_security_es_9_5_2_v1"
    count_kind: str = "lucene_live_docs"


def _supported(value: ObservedSecurityDescriptor) -> None:
    if (
        type(value) is not ObservedSecurityDescriptor
        or type(value.image) is not OriginalImageReference
        or value.image.image_id != ORIGINAL_IMAGE
    ):
        raise ValueError(_DENIED)
    expected = ObservedSecurityDescriptor(
        value.nonce, value.snapshot_sha256, value.original_deployment_sha256, value.image
    )
    for member in fields(expected):
        if member.name in {"nonce", "snapshot_sha256", "original_deployment_sha256", "image"}:
            continue
        actual, required = getattr(value, member.name), getattr(expected, member.name)
        if type(actual) is not type(required) or actual != required:
            raise ValueError(_DENIED)


def decode_main_security_inventory(
    state_raw: bytes,
    stats_raw: bytes,
    *,
    cluster_uuid: str,
    cluster_name: str,
    stable_node_id: str,
    descriptor: ObservedSecurityDescriptor,
) -> DecodedMainSecurityIndex:
    """Validate ordinary DTOs; the producer separately revalidates both issuers."""
    try:
        _supported(descriptor)
        # Reuse complete physical structural joins only, with no selected legacy
        # entries. Nothing here compares manufactured subsets or grants rights.
        physical = decode_unmanaged_inventory(
            state_raw,
            stats_raw,
            cluster_uuid=cluster_uuid,
            cluster_name=cluster_name,
            stable_node_id=stable_node_id,
            unmanaged_entries=(),
        )
        state, stats = _load(state_raw), _load(stats_raw)
        indices = _object(_object(state["metadata"])["indices"])
        name = descriptor.primary_name
        if {key for key, row in indices.items() if row["system"] is True} != {name} or {
            key for key, row in indices.items() if descriptor.alias_name in row["aliases"]
        } != {name}:
            raise ValueError(_DENIED)
        row = _object(indices[name])
        settings = _object(row["settings"])
        if (
            row["aliases"] != [descriptor.alias_name]
            or settings.get("index.hidden") != "true"
            or settings.get(descriptor.index_format_setting) != str(descriptor.index_format)
            or settings.get("index.number_of_shards") != str(descriptor.primary_shards)
            or settings.get("index.auto_expand_replicas") != descriptor.auto_expand_replicas
        ):
            raise ValueError(_DENIED)
        mapping = _object(row["mappings"])
        if "_doc" in mapping:
            if set(mapping) != {"_doc"}:
                raise ValueError(_DENIED)
            mapping = _object(mapping["_doc"])
        meta = _object(mapping.get("_meta"))
        if (
            type(meta.get(descriptor.security_version_key)) is not str
            or meta[descriptor.security_version_key] != descriptor.security_version
            or type(meta.get(descriptor.mapping_version_key)) is not int
            or meta[descriptor.mapping_version_key] != descriptor.mapping_version
        ):
            raise ValueError(_DENIED)
        nodes = _object(stats["nodes"])
        counts = _object(_object(_object(nodes[stable_node_id])["indices"])["indices"])
        count, deleted = _docs(counts[name])
        return DecodedMainSecurityIndex(
            name,
            _identifier(settings["index.uuid"]),
            count,
            _canonical({name: row}),
            physical.private_physical_inventory,
            deleted,
        )
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        raise ValueError(_DENIED) from None
