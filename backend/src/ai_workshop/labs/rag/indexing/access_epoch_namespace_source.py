"""Issue existing original namespaces from bounded source reads, never control proof."""

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select

from ai_workshop.config import Settings
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from ai_workshop.labs.rag.indexing.access_epoch_index_inventory import (
    _canonical,
    _load,
    _name,
    _object,
    _uuid,
    decode_index_listing,
    decode_index_metadata,
)
from ai_workshop.labs.rag.indexing.access_epoch_native import (
    OriginalAccessEpochPreflight,
    OriginalDeploymentObservation,
)
from ai_workshop.labs.rag.indexing.access_epoch_permissions import AccessEpochPermissions
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import validate_endpoint
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasOperationSnapshot
from ai_workshop.labs.rag.indexing.contracts import IndexDescriptor, canonical_recovery_targets
from ai_workshop.labs.rag.models.document_processing import (
    LEGACY_DOCUMENT_PROCESSING_PROFILE_ID,
    index_namespace_document_processing_profile_id,
)
from ai_workshop.labs.rag.models.models import ProfileRecord
from ai_workshop.shared.db import create_engine

_LISTING = (
    "/_cluster/state/metadata?flat_settings=true&filter_path="
    "cluster_uuid,metadata.indices.*.state,metadata.indices.*.settings.*uuid,"
    "metadata.indices.*.settings.*hidden"
)
_METADATA = (
    "/_cluster/state/metadata,routing_table?flat_settings=true&filter_path="
    "cluster_uuid,metadata.indices.*.state,metadata.indices.*.system,"
    "metadata.indices.*.settings,metadata.indices.*.mappings,metadata.indices.*.aliases"
)
_MAX_RESPONSE = 262144
_MAX_TOTAL = 16 * 1024 * 1024
_MAX_ENV_BYTES = 1024 * 1024

type _ConfigurationInputs = tuple[Path, bytes, tuple[tuple[str, str], ...], object]


def _denied() -> ValueError:
    return ValueError("original_namespace_unverified")


def _configuration(settings: Settings) -> tuple[object, ...]:
    database = urlsplit(settings.database_url)
    if (
        settings.environment != "local"
        or settings.elasticsearch_access_epoch_id is not None
        or settings.elasticsearch_access_epoch is not None
        or settings.elasticsearch_ca_certs is not None
        or settings.elasticsearch_api_key is not None
        or settings.elasticsearch_role is not None
        or settings.elasticsearch_url != "http://127.0.0.1:9200"
        or not settings.rag_index_store_id
        or not settings.rag_index_cluster_uuid
        or database.scheme != "postgresql+psycopg"
        or database.hostname != "127.0.0.1"
        or database.port != 15432
        or database.path != "/ai_workshop_local_clean"
        or database.query
        or database.fragment
    ):
        raise _denied()
    return (
        settings.environment,
        settings.elasticsearch_url,
        settings.elasticsearch_index_prefix,
        settings.rag_index_store_id,
        settings.rag_index_cluster_uuid,
        settings.database_url,
    )


@dataclass(frozen=True, slots=True, eq=False)
class _ValidatedConfiguration:
    nonce: UUID
    issuer: "OriginalNamespaceSource" = field(repr=False)
    inputs: _ConfigurationInputs = field(repr=False)
    configuration: tuple[object, ...] = field(repr=False)


def _configuration_token_signature(value: _ValidatedConfiguration) -> object:
    if (
        type(value) is not _ValidatedConfiguration
        or type(value.issuer) is not OriginalNamespaceSource
        or type(value.nonce) is not UUID
        or value.nonce.int == 0
        or type(value.inputs) is not tuple
        or len(value.inputs) != 4
        or not isinstance(value.inputs[0], Path)
        or type(value.inputs[1]) is not bytes
        or type(value.inputs[2]) is not tuple
        or type(value.configuration) is not tuple
        or any(type(part) is not str for part in value.configuration)
    ):
        raise _denied()
    for pair in value.inputs[2]:
        if type(pair) is not tuple or len(pair) != 2 or any(type(x) is not str for x in pair):
            raise _denied()
    return (
        str(value.nonce),
        id(value.issuer),
        str(value.inputs[0]),
        value.inputs[1],
        value.inputs[2],
        id(value.inputs[3]),
        value.configuration,
    )


@dataclass(frozen=True, slots=True, eq=False)
class OriginalNamespacePermissions:
    nonce: UUID
    permissions: AccessEpochPermissions = field(repr=False)
    snapshot_sha256: str
    original_deployment_sha256: str


@dataclass(frozen=True, slots=True, eq=False)
class OriginalUnmanagedPhysicalEntry:
    name: str
    uuid: str
    indexing_profile_id: UUID
    index_build_id: UUID
    prefix: str
    reason: Literal["outside_configured_prefix", "missing_indexing_profile"]
    aliases: tuple[str, ...] = field(repr=False)
    private_metadata: bytes = field(repr=False)


@dataclass(frozen=True, slots=True, eq=False)
class OriginalUnmanagedPhysical:
    nonce: UUID
    namespace_nonce: UUID
    snapshot_sha256: str
    original_deployment_sha256: str
    entries: tuple[OriginalUnmanagedPhysicalEntry, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class _NamespaceCandidate:
    name: str
    uuid: str
    profile: UUID
    build: UUID
    prefix: str
    processing: UUID
    namespace_processing: UUID | None
    tracked: bool
    aliases: tuple[str, ...] = field(repr=False)
    private_metadata: bytes = field(repr=False)


def _unmanaged_signature(value: OriginalUnmanagedPhysical) -> tuple[object, ...]:
    if (
        type(value) is not OriginalUnmanagedPhysical
        or type(value.nonce) is not UUID
        or type(value.namespace_nonce) is not UUID
        or type(value.snapshot_sha256) is not str
        or type(value.original_deployment_sha256) is not str
        or type(value.entries) is not tuple
    ):
        raise _denied()
    entries = []
    for entry in value.entries:
        if (
            type(entry) is not OriginalUnmanagedPhysicalEntry
            or any(
                type(part) is not str
                for part in (entry.name, entry.uuid, entry.prefix, entry.reason)
            )
            or type(entry.indexing_profile_id) is not UUID
            or type(entry.index_build_id) is not UUID
            or entry.reason not in {"outside_configured_prefix", "missing_indexing_profile"}
            or type(entry.aliases) is not tuple
            or any(type(alias) is not str for alias in entry.aliases)
            or type(entry.private_metadata) is not bytes
        ):
            raise _denied()
        entries.append(
            (
                id(entry),
                entry.name,
                entry.uuid,
                str(entry.indexing_profile_id),
                str(entry.index_build_id),
                entry.prefix,
                entry.reason,
                entry.aliases,
                entry.private_metadata,
            )
        )
    return (
        str(value.nonce),
        str(value.namespace_nonce),
        value.snapshot_sha256,
        value.original_deployment_sha256,
        id(value.entries),
        tuple(entries),
    )


def _signature(value: OriginalNamespacePermissions) -> tuple[object, ...]:
    if (
        type(value) is not OriginalNamespacePermissions
        or type(value.nonce) is not UUID
        or type(value.permissions) is not AccessEpochPermissions
        or type(value.permissions.prefix) is not str
        or type(value.permissions.namespaces) is not tuple
        or type(value.snapshot_sha256) is not str
        or type(value.original_deployment_sha256) is not str
    ):
        raise _denied()
    namespaces = []
    for pair in value.permissions.namespaces:
        if (
            type(pair) is not tuple
            or len(pair) != 2
            or type(pair[0]) is not UUID
            or pair[1] is not None
            and type(pair[1]) is not UUID
        ):
            raise _denied()
        namespaces.append((str(pair[0]), str(pair[1]) if pair[1] is not None else None))
    return (
        str(value.nonce),
        id(value.permissions),
        value.permissions.prefix,
        tuple(namespaces),
        value.snapshot_sha256,
        value.original_deployment_sha256,
    )


class OriginalNamespaceSource:
    def __init__(
        self,
        settings: Settings,
        original: OriginalAccessEpochPreflight,
        observation: OriginalDeploymentObservation,
    ) -> None:
        self.settings, self.original, self.observation = settings, original, observation
        self._sources = (settings, original, observation)
        self._configuration_inputs: _ValidatedConfiguration | None = None
        self._configuration_tokens: dict[_ValidatedConfiguration, object] = {}
        self._issued: dict[OriginalNamespacePermissions, tuple[object, ...]] = {}
        self._companions: dict[OriginalNamespacePermissions, OriginalUnmanagedPhysical] = {}
        self._unmanaged: dict[
            OriginalUnmanagedPhysical, tuple[tuple[object, ...], OriginalNamespacePermissions]
        ] = {}
        try:
            self._context = _configuration(settings)
            self._guard()
        except Exception:
            raise _denied() from None

    def _guard(self) -> None:
        if (
            any(
                current is not retained
                for current, retained in zip(
                    (self.settings, self.original, self.observation), self._sources, strict=True
                )
            )
            or type(self.original) is not OriginalAccessEpochPreflight
            or type(self.observation) is not OriginalDeploymentObservation
            or self.settings is not self.original.settings
            or _configuration(self.settings) != self._context
        ):
            raise _denied()
        self.original.assert_observed(self.observation)
        validate_endpoint(self.settings.elasticsearch_url, os.environ)
        path = PROJECT_ROOT / ".env"
        before = self._configuration_input(path)
        cached = self._configuration_inputs
        if cached is not None and (
            type(cached) is not _ValidatedConfiguration
            or cached.issuer is not self
            or self._configuration_tokens.get(cached) != _configuration_token_signature(cached)
            or cached.configuration != self._context
        ):
            raise _denied()
        if cached is None or cached.inputs != before:
            fresh = Settings(_env_file=path)  # type: ignore[call-arg]
            configuration = _configuration(fresh)
            if configuration != self._context:
                raise _denied()
            if self._configuration_input(path) != before:
                raise _denied()
            validated = _ValidatedConfiguration(uuid4(), self, before, configuration)
            signature = _configuration_token_signature(validated)
            self._configuration_tokens.clear()
            self._configuration_tokens[validated] = signature
            self._configuration_inputs = validated

    @staticmethod
    def _configuration_input(path: Path) -> _ConfigurationInputs:
        # Always reread source bytes/environment; only expensive parsing is cached.
        # Private source material stays in this instance's RAM, never a manifest.
        if path.is_symlink() or not path.is_file() or path.stat().st_size > _MAX_ENV_BYTES:
            raise _denied()
        data = path.read_bytes()
        if len(data) > _MAX_ENV_BYTES:
            raise _denied()
        return (path, data, tuple(sorted(os.environ.items())), Settings)

    async def _read(self, path: str) -> bytes:
        self._guard()
        async with (
            httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=10) as client,
            client.stream(
                "GET", "http://127.0.0.1:9200" + path, headers={"Accept-Encoding": "identity"}
            ) as response,
        ):
            if (
                response.status_code != 200
                or response.headers.get("content-encoding", "identity") != "identity"
            ):
                raise _denied()
            chunks = bytearray()
            async for part in response.aiter_bytes(chunk_size=16384):
                if len(chunks) + len(part) > _MAX_RESPONSE:
                    raise _denied()
                chunks.extend(part)
        self._guard()
        return bytes(chunks)

    def _namespaces(
        self, raw: bytes, listing_raw: bytes
    ) -> tuple[tuple[_NamespaceCandidate, ...], dict[UUID, str], dict[str, tuple[str, ...]]]:
        listing = decode_index_listing(listing_raw)
        packet = _load(raw)
        if (
            set(packet) != {"cluster_uuid", "metadata"}
            or packet["cluster_uuid"] != self.observation.identity.cluster_uuid
            or listing.cluster_uuid != packet["cluster_uuid"]
            or set(_object(packet["metadata"])) != {"indices"}
            or not 0 < len(listing.indices) <= 64
        ):
            raise _denied()
        indices = _object(packet["metadata"]["indices"])
        if set(indices) != {row.name for row in listing.indices}:
            raise _denied()
        prefix = self.settings.elasticsearch_index_prefix
        candidates: list[_NamespaceCandidate] = []
        expected: dict[UUID, str] = {}
        aliases_by_index: dict[str, tuple[str, ...]] = {}
        for item in listing.indices:
            row = _object(indices[item.name])
            if (
                set(row) != {"state", "settings", "mappings", "aliases", "system"}
                or type(row["system"]) is not bool
                or row["state"] != item.state
            ):
                raise _denied()
            settings = _object(row["settings"])
            if settings.get("index.uuid") != item.uuid or settings.get("index.hidden", "false") != (
                "true" if item.hidden else "false"
            ):
                raise _denied()
            aliases = row["aliases"]
            if (
                type(aliases) is not list
                or any(type(a) is not str for a in aliases)
                or len(set(aliases)) != len(aliases)
            ):
                raise _denied()
            aliases_by_index[item.name] = tuple(_name(alias) for alias in aliases)
            mapping = _object(row["mappings"])
            if "_doc" in mapping:
                if set(mapping) != {"_doc"}:
                    raise _denied()
                mapping = _object(mapping["_doc"])
            meta = _object(mapping.get("_meta", {}))
            properties = _object(mapping.get("properties", {}))
            if "rag" not in meta and "rag_index_resource" not in meta:
                if item.name.startswith(prefix + "-") or set(properties) & {
                    "rag_mapping_version",
                    "indexing_profile_id",
                    "index_build_id",
                    "projection_id",
                }:
                    raise _denied()
                continue
            if row["system"] is not False or item.hidden or item.state != "open":
                raise _denied()
            rag = _object(meta.get("rag"))
            profile = UUID(_uuid(rag.get("indexing_profile_id")))
            build = UUID(_uuid(rag.get("index_build_id")))
            inside = item.name.startswith(prefix + "-")
            actual_prefix = prefix
            if not inside:
                suffix = f"-{profile}-{build}"
                if "rag_index_resource" in meta or not item.name.endswith(suffix):
                    raise _denied()
                actual_prefix = item.name.removesuffix(suffix)
            processing = LEGACY_DOCUMENT_PROCESSING_PROFILE_ID
            if "rag_index_resource" in meta:
                resource = _object(meta["rag_index_resource"])
                processing = UUID(_uuid(resource.get("document_processing_profile_id")))
            namespace_processing = index_namespace_document_processing_profile_id(processing)
            one = AccessEpochPermissions(actual_prefix, ((profile, namespace_processing),))
            descriptor = IndexDescriptor(1, "cosine")
            if (
                item.name
                != descriptor.concrete_index_name(
                    actual_prefix,
                    profile,
                    build,
                    document_processing_profile_id=namespace_processing,
                )
                or inside
                and any(alias != one.aliases[0] for alias in aliases)
            ):
                raise _denied()
            # Cluster state supplies alias names only. These empty objects adapt
            # membership for structural validation, never prove alias definitions.
            decode_index_metadata(
                item.name,
                one,
                _canonical(
                    {
                        item.name: {
                            "aliases": {alias: {} for alias in aliases},
                            "settings": settings,
                            "defaults": {},
                            "mappings": mapping,
                        }
                    }
                ),
            )
            if inside:
                for identifier, kind in (
                    (profile, "indexing"),
                    (processing, "document_processing"),
                ):
                    if identifier in expected and expected[identifier] != kind:
                        raise _denied()
                    expected[identifier] = kind
            candidates.append(
                _NamespaceCandidate(
                    item.name,
                    item.uuid,
                    profile,
                    build,
                    actual_prefix,
                    processing,
                    namespace_processing,
                    "rag_index_resource" in meta,
                    tuple(aliases),
                    _canonical({item.name: row}),
                )
            )
        return tuple(candidates), expected, aliases_by_index

    def _classify(
        self,
        snapshot: AliasOperationSnapshot,
        candidates: tuple[_NamespaceCandidate, ...],
        expected: dict[UUID, str],
        found: dict[UUID, str],
        aliases_by_index: dict[str, tuple[str, ...]],
    ) -> tuple[AccessEpochPermissions, tuple[OriginalUnmanagedPhysicalEntry, ...]]:
        missing = set(expected) - set(found)
        if len(missing) > 1 or any(
            expected[identifier] != "indexing" or identifier == snapshot.indexing_profile_id
            for identifier in missing
        ):
            raise _denied()
        selected = (
            (snapshot.indexing_profile_id, "indexing"),
            (snapshot.document_processing_profile_id, "document_processing"),
        )
        if any(
            expected.get(identifier) != kind or found.get(identifier) != kind
            for identifier, kind in selected
        ):
            raise _denied()
        namespaces: set[tuple[UUID, UUID | None]] = {
            (
                snapshot.indexing_profile_id,
                index_namespace_document_processing_profile_id(
                    snapshot.document_processing_profile_id
                ),
            )
        }
        rag_names: set[str] = set()
        unmanaged = []
        prefix = self.settings.elasticsearch_index_prefix
        for candidate in candidates:
            reason: Literal["outside_configured_prefix", "missing_indexing_profile"]
            if candidate.prefix != prefix:
                reason = "outside_configured_prefix"
            elif candidate.profile in missing:
                if candidate.tracked or candidate.name in snapshot.targets:
                    raise _denied()
                reason = "missing_indexing_profile"
            else:
                namespaces.add((candidate.profile, candidate.namespace_processing))
                rag_names.add(candidate.name)
                continue
            unmanaged.append(
                OriginalUnmanagedPhysicalEntry(
                    candidate.name,
                    candidate.uuid,
                    candidate.profile,
                    candidate.build,
                    candidate.prefix,
                    reason,
                    candidate.aliases,
                    candidate.private_metadata,
                )
            )
        if not namespaces:
            raise _denied()
        permissions = AccessEpochPermissions(
            prefix,
            tuple(
                sorted(
                    namespaces,
                    key=lambda pair: (str(pair[0]), str(pair[1]) if pair[1] else ""),
                )
            ),
        )
        if any(
            set(aliases) & set(permissions.aliases)
            for name, aliases in aliases_by_index.items()
            if name not in rag_names
        ):
            raise _denied()
        if any(snapshot.alias in entry.aliases for entry in unmanaged):
            raise _denied()
        return permissions, tuple(sorted(unmanaged, key=lambda entry: entry.name))

    async def _profiles(self, expected: dict[UUID, str]) -> dict[UUID, str]:
        self._guard()
        # At most 64 physical profile pairs and one exact reserved pair.
        # Fetch one sentinel beyond the entire scope: truncation is not absence.
        if not 0 < len(expected) <= 130 or any(
            type(identifier) is not UUID
            or identifier.int == 0
            or kind not in {"indexing", "document_processing"}
            for identifier, kind in expected.items()
        ):
            raise _denied()
        engine = create_engine(self.settings)
        try:
            async with engine.connect() as connection:
                rows = (
                    await connection.execute(
                        select(ProfileRecord.id, ProfileRecord.kind)
                        .where(ProfileRecord.id.in_(tuple(expected)))
                        .limit(len(expected) + 1)
                    )
                ).all()
            if (
                len(rows) > len(expected)
                or any(
                    len(row) != 2 or type(row[0]) is not UUID or type(row[1]) is not str
                    for row in rows
                )
                or len({row[0] for row in rows}) != len(rows)
                or any(row[0] not in expected or row[1] != expected[row[0]] for row in rows)
            ):
                raise _denied()
        finally:
            await engine.dispose()
        self._guard()
        return {row[0]: row[1] for row in rows}

    async def observe(self, snapshot: AliasOperationSnapshot) -> OriginalNamespacePermissions:
        try:
            async with asyncio.timeout(60):
                self._guard()
                if (
                    type(snapshot) is not AliasOperationSnapshot
                    or snapshot.sha256 != self.observation.snapshot_sha256
                    or (snapshot.store_id, snapshot.cluster_uuid)
                    != (self.settings.rag_index_store_id, self.settings.rag_index_cluster_uuid)
                ):
                    raise _denied()
                before = await self.original.observe_original(snapshot)
                self._guard()
                if before != self.observation.identity:
                    raise _denied()
                listing = await self._read(_LISTING)
                first = await self._read(_METADATA)
                candidates, expected, aliases = self._namespaces(first, listing)
                # A reserved target can precede its first physical index. Admit
                # only its exact DB-backed pair, never a DB-wide cross product.
                for identifier, kind in (
                    (snapshot.indexing_profile_id, "indexing"),
                    (snapshot.document_processing_profile_id, "document_processing"),
                ):
                    if (
                        type(identifier) is not UUID
                        or identifier.int == 0
                        or identifier in expected
                        and expected[identifier] != kind
                    ):
                        raise _denied()
                    expected[identifier] = kind
                first_profiles = await self._profiles(expected)
                permissions, unmanaged_entries = self._classify(
                    snapshot, candidates, expected, first_profiles, aliases
                )
                second = await self._read(_METADATA)
                second_profiles = await self._profiles(expected)
                final_listing = await self._read(_LISTING)
                if (
                    sum(map(len, (listing, first, second, final_listing))) > _MAX_TOTAL
                    or decode_index_listing(listing) != decode_index_listing(final_listing)
                    or _canonical(_load(first)) != _canonical(_load(second))
                    or first_profiles != second_profiles
                ):
                    raise _denied()
                self._namespaces(second, final_listing)
                processing = index_namespace_document_processing_profile_id(
                    snapshot.document_processing_profile_id
                )
                if (
                    snapshot.indexing_profile_id,
                    processing,
                ) not in permissions.namespaces or snapshot.alias != IndexDescriptor(
                    1, "cosine"
                ).active_alias(
                    permissions.prefix,
                    snapshot.indexing_profile_id,
                    document_processing_profile_id=processing,
                ):
                    raise _denied()
                if snapshot.targets:
                    canonical_recovery_targets(snapshot.alias, snapshot.targets)
                    if not set(snapshot.targets) <= {
                        row.name for row in decode_index_listing(listing).indices
                    }:
                        raise _denied()
                    if set(snapshot.targets) & {entry.name for entry in unmanaged_entries}:
                        raise _denied()
                after = await self.original.observe_original(snapshot)
                self._guard()
                if (
                    after != before
                    or after != self.observation.identity
                    or snapshot.sha256 != self.observation.snapshot_sha256
                ):
                    raise _denied()
                value = OriginalNamespacePermissions(
                    uuid4(),
                    permissions,
                    snapshot.sha256,
                    self.observation.identity.deployment_sha256,
                )
                unmanaged = OriginalUnmanagedPhysical(
                    uuid4(),
                    value.nonce,
                    value.snapshot_sha256,
                    value.original_deployment_sha256,
                    unmanaged_entries,
                )
                signature, unmanaged_signature = _signature(value), _unmanaged_signature(unmanaged)
                self._issued[value] = signature
                self._companions[value] = unmanaged
                self._unmanaged[unmanaged] = (unmanaged_signature, value)
                return value
        except Exception:
            raise _denied() from None

    def assert_issued(self, value: OriginalNamespacePermissions) -> None:
        try:
            self._guard()
            self._assert_pair(value, self._companions[value])
        except Exception:
            raise _denied() from None

    def _assert_pair(
        self, value: OriginalNamespacePermissions, unmanaged: OriginalUnmanagedPhysical
    ) -> None:
        retained = self._unmanaged.get(unmanaged)
        if (
            self._issued.get(value) != _signature(value)
            or self._companions.get(value) is not unmanaged
            or retained is None
            or retained[1] is not value
            or retained[0] != _unmanaged_signature(unmanaged)
            or unmanaged.namespace_nonce != value.nonce
            or unmanaged.snapshot_sha256 != value.snapshot_sha256
            or unmanaged.original_deployment_sha256 != value.original_deployment_sha256
        ):
            raise _denied()

    def unmanaged(self, value: OriginalNamespacePermissions) -> OriginalUnmanagedPhysical:
        try:
            self.assert_issued(value)
            return self._companions[value]
        except Exception:
            raise _denied() from None

    def assert_unmanaged_issued(self, value: OriginalUnmanagedPhysical) -> None:
        try:
            self._guard()
            retained = self._unmanaged.get(value)
            if retained is None:
                raise _denied()
            self._assert_pair(retained[1], value)
        except Exception:
            raise _denied() from None
