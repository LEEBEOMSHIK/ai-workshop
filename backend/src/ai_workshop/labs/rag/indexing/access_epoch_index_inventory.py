"""Pure bounded index decoders, never native observation/source-authority issuers.

Only closed public projections are hashed. Full metadata (including arbitrary
analysis, aliases and user metadata) must remain in protected private storage.
The composing producer must prove complete listing, quiescence, actual captures
and private equality before using these ordinary DTOs as preservation inputs.
"""

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import UUID

from ai_workshop.labs.rag.indexing.access_epoch_observations import IndexObservation
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, canonical_recovery_targets

_DENIED = "index_inventory_decode_denied"
_MISMATCH = "index_inventory_preservation_mismatch"
_MAX_BYTES = 256 * 1024
_MAX_INDICES = 1024
_MAX_INT = 2**63 - 1
_NAME = re.compile(r"[a-z0-9.][a-z0-9._-]{0,254}")
_IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,128}")
_HEX = re.compile(r"[0-9a-f]{64}")


class _FloatToken(str):
    """Preserve private numeric tokens without float-rounding information loss."""


@dataclass(frozen=True, slots=True)
class ListedIndex:
    name: str
    uuid: str
    state: str
    hidden: bool


@dataclass(frozen=True, slots=True)
class DecodedIndexListing:
    cluster_uuid: str
    indices: tuple[ListedIndex, ...]
    private_listing: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class DecodedIndexMetadata:
    name: str
    uuid: str
    schema: Literal["tracked_v1", "legacy_rag_v1"]
    private_metadata: bytes = field(repr=False)
    _permissions: AccessEpochPermissions = field(repr=False)
    _public_settings: bytes = field(repr=False)
    _public_provenance: bytes = field(repr=False)
    _count_body: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class PrivateCountBody:
    body: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class DecodedIndexInventoryEntry:
    observation: IndexObservation
    private_metadata: bytes = field(repr=False)


def _object(value: object) -> dict[str, Any]:
    if type(value) is not dict:
        raise ValueError(_DENIED)
    return value


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(_DENIED)
        result[key] = value
    return result


def _float(token: str) -> _FloatToken:
    if len(token) > 64 or not math.isfinite(float(token)):
        raise ValueError(_DENIED)
    return _FloatToken(token)


def _constant(_: str) -> None:
    raise ValueError(_DENIED)


def _canonical(value: object) -> bytes:
    def encode(item: object) -> str:
        if type(item) is _FloatToken:
            return str(item)
        if type(item) is dict:
            return (
                "{"
                + ",".join(
                    json.dumps(key, ensure_ascii=True) + ":" + encode(item[key])
                    for key in sorted(item)
                )
                + "}"
            )
        if type(item) is list:
            return "[" + ",".join(encode(child) for child in item) + "]"
        return json.dumps(item, ensure_ascii=True, allow_nan=False, separators=(",", ":"))

    packet = encode(value).encode("ascii")
    if len(packet) > _MAX_BYTES:
        raise ValueError(_DENIED)
    return packet


def _load(raw: bytes) -> dict[str, Any]:
    try:
        if type(raw) is not bytes or not 1 <= len(raw) <= _MAX_BYTES:
            raise ValueError(_DENIED)
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=_float,
            parse_constant=_constant,
        )
        pending: list[tuple[object, int]] = [(value, 0)]
        nodes = 0
        while pending:
            item, depth = pending.pop()
            nodes += 1
            if depth > 32 or nodes > 32768:
                raise ValueError(_DENIED)
            if type(item) is str:
                if len(item) > 16384:
                    raise ValueError(_DENIED)
                item.encode("utf-8")  # Reject lone surrogates even in private fields.
            elif type(item) is int:
                if not -_MAX_INT <= item <= _MAX_INT:
                    raise ValueError(_DENIED)
            elif type(item) is dict:
                pending.extend((part, depth + 1) for pair in item.items() for part in pair)
            elif type(item) is list:
                pending.extend((part, depth + 1) for part in item)
        return _object(value)
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise ValueError(_DENIED) from None


def _identifier(value: object) -> str:
    if type(value) is not str or _IDENTIFIER.fullmatch(value) is None:
        raise ValueError(_DENIED)
    return value


def _name(value: object) -> str:
    if type(value) is not str or _NAME.fullmatch(value) is None or value in {".", ".."}:
        raise ValueError(_DENIED)
    return value


def _uuid(value: object) -> str:
    try:
        if type(value) is not str or str(UUID(value)) != value:
            raise ValueError(_DENIED)
        return value
    except ValueError:
        raise ValueError(_DENIED) from None


def _integer(value: object, minimum: int = 0, maximum: int = _MAX_INT) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError(_DENIED)
    return value


def _decimal(value: object, minimum: int = 0, maximum: int = _MAX_INT) -> int:
    if type(value) is not str or re.fullmatch(r"0|[1-9][0-9]{0,18}", value) is None:
        raise ValueError(_DENIED)
    return _integer(int(value), minimum, maximum)


def decode_index_listing(raw: bytes) -> DecodedIndexListing:
    """Retain every physical entry; security and foreign names are not exempted."""
    body = _load(raw)
    if set(body) != {"cluster_uuid", "metadata"}:
        raise ValueError(_DENIED)
    cluster = _identifier(body["cluster_uuid"])
    metadata = _object(body["metadata"])
    if set(metadata) != {"indices"}:
        raise ValueError(_DENIED)
    indices = _object(metadata["indices"])
    if len(indices) > _MAX_INDICES:
        raise ValueError(_DENIED)
    rows: list[ListedIndex] = []
    for name, raw_index in sorted(indices.items()):
        index = _object(raw_index)
        if set(index) != {"state", "settings"} or index["state"] not in ("open", "close"):
            raise ValueError(_DENIED)
        settings = _object(index["settings"])
        if set(settings) not in ({"index.uuid"}, {"index.uuid", "index.hidden"}):
            raise ValueError(_DENIED)
        hidden = settings.get("index.hidden", "false")
        if type(hidden) is not str or hidden not in {"true", "false"}:
            raise ValueError(_DENIED)
        rows.append(
            ListedIndex(
                _name(name), _identifier(settings["index.uuid"]), index["state"], hidden == "true"
            )
        )
    if len({row.uuid for row in rows}) != len(rows):
        raise ValueError(_DENIED)
    return DecodedIndexListing(cluster, tuple(rows), _canonical(body))


def _namespace(name: str, permissions: AccessEpochPermissions) -> tuple[str, str | None]:
    if type(permissions) is not AccessEpochPermissions:
        raise ValueError(_DENIED)
    matches: list[tuple[str, str | None]] = []
    for profile, processing in permissions.namespaces:
        if type(profile) is not UUID or (processing is not None and type(processing) is not UUID):
            raise ValueError(_DENIED)
        alias = IndexDescriptor(1, "cosine").active_alias(
            permissions.prefix, profile, document_processing_profile_id=processing
        )
        try:
            canonical_recovery_targets(alias, (name,))
        except ValueError:
            continue
        matches.append((str(profile), str(processing) if processing is not None else None))
    if len(matches) != 1:
        raise ValueError(_DENIED)
    return matches[0]


def _settings_projection(settings: dict[str, Any], defaults: dict[str, Any]) -> bytes:
    projection: dict[str, object] = {
        "contract": "public_index_settings_v1",
        "uuid": _identifier(settings.get("index.uuid")),
        "creation_date": _decimal(settings.get("index.creation_date")),
        "number_of_shards": _decimal(settings.get("index.number_of_shards"), 1, 1024),
        "number_of_replicas": _decimal(settings.get("index.number_of_replicas"), 0, 1024),
        "version_created": _decimal(settings.get("index.version.created"), 1),
    }
    refresh = settings.get("index.refresh_interval", defaults.get("index.refresh_interval"))
    if "index.refresh_interval" in settings or "index.refresh_interval" in defaults:
        if type(refresh) is not str:
            raise ValueError(_DENIED)
        if refresh == "-1":
            projection["refresh_interval_ms"] = -1
        else:
            match = re.fullmatch(r"(0|[1-9][0-9]{0,12})(ms|s|m|h|d)", refresh)
            if match is None:
                raise ValueError(_DENIED)
            multiplier = {"ms": 1, "s": 1000, "m": 60000, "h": 3600000, "d": 86400000}
            projection["refresh_interval_ms"] = _integer(
                int(match[1]) * multiplier[match[2]], maximum=_MAX_INT
            )
    return _canonical(projection)


def decode_index_metadata(
    name: str, permissions: AccessEpochPermissions, raw: bytes
) -> DecodedIndexMetadata:
    """Decode explicit tracked/known legacy schemas, without source authority."""
    name = _name(name)
    profile, processing = _namespace(name, permissions)
    body = _load(raw)
    if set(body) != {name}:
        raise ValueError(_DENIED)
    metadata = _object(body[name])
    if set(metadata) != {"aliases", "settings", "defaults", "mappings"}:
        raise ValueError(_DENIED)
    aliases = _object(metadata["aliases"])
    for alias, alias_value in aliases.items():
        _name(alias)
        _object(alias_value)
    settings = _object(metadata["settings"])
    defaults = _object(metadata["defaults"])
    mappings = _object(metadata["mappings"])
    _object(mappings.get("properties"))
    meta = _object(mappings.get("_meta"))
    rag = _object(meta.get("rag"))
    _integer(rag.get("mapping_version"), 1, 1)
    ids = {
        key: _uuid(rag.get(key))
        for key in ("index_build_id", "projection_id", "indexing_profile_id")
    }
    if ids["index_build_id"] != name[-36:] or ids["indexing_profile_id"] != profile:
        raise ValueError(_DENIED)
    provenance: dict[str, object] = {
        "contract": "public_index_provenance_counts_v1",
        "mapping_version": 1,
        **ids,
        "vector_dimension": _integer(rag.get("vector_dimension"), 1, 65536),
    }
    terms: dict[str, object] = {
        "projection_id": ids["projection_id"],
        "index_build_id": ids["index_build_id"],
        "indexing_profile_id": ids["indexing_profile_id"],
        "rag_mapping_version": 1,
    }
    schema: Literal["tracked_v1", "legacy_rag_v1"]
    if "rag_index_resource" not in meta:
        # Absence is an explicit legacy variant, never recovery from malformed
        # tracked metadata. This variant has no processing/source-location claim.
        if processing is not None:
            raise ValueError(_DENIED)
        schema = "legacy_rag_v1"
    else:
        resource = _object(meta["rag_index_resource"])
        _integer(resource.get("contract_version"), 1, 1)
        resource_ids = {
            key: _uuid(resource.get(key))
            for key in (
                "resource_id",
                "job_id",
                "workspace_id",
                "document_id",
                "asset_version_id",
                "document_processing_profile_id",
            )
        }
        if resource_ids["resource_id"] != ids["index_build_id"] or (
            processing is not None and resource_ids["document_processing_profile_id"] != processing
        ):
            raise ValueError(_DENIED)
        for key in ("input_fingerprint", "chunk_ids_sha256"):
            value = resource.get(key)
            if type(value) is not str or _HEX.fullmatch(value) is None:
                raise ValueError(_DENIED)
        schema = "tracked_v1"
        provenance.update(
            resource_id=resource_ids["resource_id"],
            asset_version_id=resource_ids["asset_version_id"],
            document_processing_profile_id=resource_ids["document_processing_profile_id"],
        )
        terms.update(
            asset_version_id=resource_ids["asset_version_id"],
            workspace_id=resource_ids["workspace_id"],
        )
    provenance["schema"] = schema
    properties = _object(mappings["properties"])
    runtime = _object(mappings.get("runtime", {}))
    for key in terms:
        expected_type = "integer" if key == "rag_mapping_version" else "keyword"
        if properties.get(key) != {"type": expected_type} or key in runtime:
            raise ValueError(_DENIED)
    query = {
        "query": {"bool": {"filter": [{"term": {key: value}} for key, value in terms.items()]}}
    }
    return DecodedIndexMetadata(
        name,
        _identifier(settings.get("index.uuid")),
        schema,
        _canonical(body),
        permissions,
        _settings_projection(settings, defaults),
        _canonical(provenance),
        _canonical(query),
    )


def _checked_metadata(metadata: DecodedIndexMetadata) -> None:
    # Structural self-consistency only, deliberately not an issuance capability.
    if type(metadata) is not DecodedIndexMetadata or metadata != decode_index_metadata(
        metadata.name, metadata._permissions, metadata.private_metadata
    ):
        raise ValueError(_DENIED)


def provenance_count_body(metadata: DecodedIndexMetadata) -> PrivateCountBody:
    _checked_metadata(metadata)
    return PrivateCountBody(metadata._count_body)


def _count(raw: bytes, expected_shards: int) -> int:
    body = _load(raw)
    if set(body) != {"count", "_shards"}:
        raise ValueError(_DENIED)
    shards = _object(body["_shards"])
    if set(shards) != {"total", "successful", "skipped", "failed"}:
        raise ValueError(_DENIED)
    total = _integer(shards["total"], 1)
    if (
        total != expected_shards
        or _integer(shards["successful"]) != total
        or _integer(shards["skipped"]) != 0
        or _integer(shards["failed"]) != 0
    ):
        raise ValueError(_DENIED)
    return _integer(body["count"])


def decode_index_counts(
    metadata: DecodedIndexMetadata, total_raw: bytes, provenance_raw: bytes
) -> DecodedIndexInventoryEntry:
    _checked_metadata(metadata)
    # The fixed request addresses one concrete index with no routing restriction.
    expected_shards = _integer(_load(metadata._public_settings)["number_of_shards"], 1, 1024)
    total, matched = _count(total_raw, expected_shards), _count(provenance_raw, expected_shards)
    if total != matched:
        raise ValueError(_DENIED)
    provenance = _load(metadata._public_provenance)
    provenance.update(total_count=total, provenance_count=matched)
    return DecodedIndexInventoryEntry(
        IndexObservation(
            name=metadata.name,
            uuid=metadata.uuid,
            count=total,
            settings_sha256=hashlib.sha256(metadata._public_settings).hexdigest(),
            provenance_sha256=hashlib.sha256(_canonical(provenance)).hexdigest(),
        ),
        metadata.private_metadata,
    )


def require_same_private_inventory(
    before: tuple[DecodedIndexInventoryEntry, ...], after: tuple[DecodedIndexInventoryEntry, ...]
) -> None:
    """Compare complete private packets, never just their public summaries."""
    for entries in (before, after):
        if type(entries) is not tuple or len(entries) > _MAX_INDICES:
            raise ValueError(_MISMATCH)
        if any(type(entry) is not DecodedIndexInventoryEntry for entry in entries):
            raise ValueError(_MISMATCH)
        names = tuple(entry.observation.name for entry in entries)
        if names != tuple(sorted(set(names))):
            raise ValueError(_MISMATCH)
    if before != after:
        raise ValueError(_MISMATCH)
