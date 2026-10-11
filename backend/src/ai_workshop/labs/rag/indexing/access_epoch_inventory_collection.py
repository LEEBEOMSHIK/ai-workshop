"""Join complete recorded samples; this is not an atomic ES/body snapshot.

Writer settlement, allowed system-index transitions, cross-deployment preservation
and final proof remain separate. No security-prefix exemption is inferred here.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from ai_workshop.labs.rag.indexing.access_epoch_foreign_inventory import (
    DecodedForeignInventory,
    decode_foreign_inventory,
    require_same_private_foreign_inventory,
)
from ai_workshop.labs.rag.indexing.access_epoch_index_inventory import (
    DecodedIndexInventoryEntry,
    DecodedIndexListing,
    _canonical,
    _identifier,
    _integer,
    _load,
    _object,
    decode_index_counts,
    decode_index_listing,
    decode_index_metadata,
    require_same_private_inventory,
)
from ai_workshop.labs.rag.indexing.access_epoch_inventory_commands import InventoryCommand
from ai_workshop.labs.rag.indexing.access_epoch_inventory_process import (
    CapturedInventoryRead,
    RecordedInventoryReads,
)
from ai_workshop.labs.rag.indexing.access_epoch_namespace_source import (
    OriginalNamespacePermissions,
    OriginalNamespaceSource,
    OriginalUnmanagedPhysical,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    ReservedCutoverAction,
)
from ai_workshop.labs.rag.indexing.access_epoch_unmanaged_inventory import (
    DecodedUnmanagedLegacyInventory,
    decode_unmanaged_inventory,
    require_same_unmanaged_entries,
)

if TYPE_CHECKING:
    from ai_workshop.labs.rag.indexing.access_epoch_security_inventory_native import (
        MainSecurityCompletion,
        NativeSecurityInventory,
    )

_GLOBAL = ("cluster_info", "cluster_state", "identity_state", "nodes_info", "nodes_docs")


def _denied() -> ValueError:
    return ValueError("inventory_collection_denied")


def _none(check: Callable[..., object], *args: object) -> None:
    if check(*args) is not None:
        raise _denied()


@dataclass(frozen=True, slots=True)
class InventoryTopology:
    cluster_uuid: str
    cluster_name: str
    stable_node_id: str
    ephemeral_id: str
    jvm_start_at: datetime


@dataclass(frozen=True, slots=True, eq=False)
class CapturedPhysicalInventory:
    """Source-bound raw sample; no foreign/security completion claim."""

    nonce: UUID
    parent: ReservedCutoverAction = field(repr=False)
    phase: str
    topology: InventoryTopology
    listings: tuple[DecodedIndexListing, ...] = field(repr=False)
    first_packets: tuple[tuple[str, bytes], ...] = field(repr=False)
    last_packets: tuple[tuple[str, bytes], ...] = field(repr=False)
    rag_entries: tuple[DecodedIndexInventoryEntry, ...] = field(repr=False)
    unmanaged_passes: tuple[DecodedUnmanagedLegacyInventory, ...] = field(repr=False)
    captures: tuple[CapturedInventoryRead, ...] = field(repr=False)
    namespace_source: OriginalNamespaceSource = field(repr=False)
    namespace: OriginalNamespacePermissions = field(repr=False)
    unmanaged_source: OriginalUnmanagedPhysical = field(repr=False)

    @property
    def parent_action_id(self) -> UUID:
        return self.parent.action_id


@dataclass(frozen=True, slots=True, eq=False)
class CapturedIndexInventory:
    nonce: UUID
    parent_action_id: UUID
    phase: str
    topology: InventoryTopology
    rag_entries: tuple[DecodedIndexInventoryEntry, ...]
    foreign: DecodedForeignInventory
    cluster_bytes: bytes = field(repr=False)
    identity_bytes: bytes = field(repr=False)
    nodes_bytes: bytes = field(repr=False)
    captures: tuple[CapturedInventoryRead, ...] = field(repr=False)
    physical: CapturedPhysicalInventory | None = field(default=None, repr=False)
    unmanaged: DecodedUnmanagedLegacyInventory | None = field(default=None, repr=False)


_InventoryPass = tuple[
    tuple[DecodedIndexInventoryEntry, ...],
    DecodedForeignInventory,
    InventoryTopology,
    dict[str, bytes],
]
_PhysicalPass = tuple[
    tuple[DecodedIndexInventoryEntry, ...],
    DecodedUnmanagedLegacyInventory,
    InventoryTopology,
    dict[str, bytes],
]


def _frozen(value: object) -> object:
    """Retain immutable primitive snapshots, including nested dataclass identity."""
    if value is None or type(value) in (str, int, bool, bytes):
        return (type(value), value)
    if type(value) is UUID:
        return (UUID, str(value))
    if isinstance(value, StrEnum):
        return (type(value), str(value))
    if type(value) is datetime:
        if value.utcoffset() != timedelta(0):
            raise _denied()
        return (datetime, value.isoformat())
    if type(value) is tuple:
        return tuple(_frozen(item) for item in value)
    if is_dataclass(value) and not isinstance(value, type):
        return (
            type(value),
            id(value),
            tuple((f.name, _frozen(getattr(value, f.name))) for f in fields(value)),
        )
    raise _denied()


class RecordedInventoryCollector:
    def __init__(
        self,
        reader: RecordedInventoryReads,
        *,
        namespace_source: OriginalNamespaceSource | None = None,
        namespace: OriginalNamespacePermissions | None = None,
    ) -> None:
        self.reader = reader
        self._reader = reader
        self._binding = reader.binding
        self.namespace_source, self.namespace = namespace_source, namespace
        if (namespace_source is None) != (namespace is None) or (
            namespace_source is not None
            and (
                type(namespace_source) is not OriginalNamespaceSource
                or type(namespace) is not OriginalNamespacePermissions
            )
        ):
            raise _denied()
        self._unmanaged = (
            namespace_source.unmanaged(namespace)
            if namespace_source is not None and namespace is not None
            else None
        )
        self._source_pair = (namespace_source, namespace, self._unmanaged)
        self._issued: dict[CapturedIndexInventory, tuple[object, ...]] = {}
        self._physical: dict[CapturedPhysicalInventory, object] = {}
        self._secure: dict[
            CapturedIndexInventory, tuple[NativeSecurityInventory, MainSecurityCompletion]
        ] = {}
        self._secure_signatures: dict[CapturedIndexInventory, object] = {}
        self._attempted = False
        self._completion_attempted = False
        self._captures: list[CapturedInventoryRead] = []
        self._total = 0
        self._owned()

    def _owned(self) -> None:
        if (
            type(self.reader) is not RecordedInventoryReads
            or self.reader is not self._reader
            or self.reader.binding is not self._binding
        ):
            raise _denied()
        _none(self.reader.factory.assert_issued, self._binding)
        if self.reader.commands.binding is not self._binding:
            raise _denied()
        if self._source_pair != (None, None, None):
            source, namespace, unmanaged = self.namespace_source, self.namespace, self._unmanaged
            if (
                type(source) is not OriginalNamespaceSource
                or type(namespace) is not OriginalNamespacePermissions
                or type(unmanaged) is not OriginalUnmanagedPhysical
                or any(
                    a is not b
                    for a, b in zip(self._source_pair, (source, namespace, unmanaged), strict=True)
                )
                or namespace.permissions is not self._binding.permissions
                or source.observation.identity != self.reader.factory.epoch.original
                or namespace.original_deployment_sha256
                != self.reader.factory.epoch.original.deployment_sha256
                or namespace.snapshot_sha256
                != self.reader.factory.epoch.binding.claim.snapshot.sha256
            ):
                raise _denied()
            _none(source.assert_issued, namespace)
            _none(source.assert_unmanaged_issued, unmanaged)
            if source.unmanaged(namespace) is not unmanaged:
                raise _denied()

    async def _read(
        self, parent: ReservedCutoverAction, command: InventoryCommand, round: int
    ) -> bytes:
        self._owned()
        captured = await self.reader.read(parent, command, round)
        self._owned()
        _none(self.reader.assert_issued, captured)
        if (
            type(captured) is not CapturedInventoryRead
            or captured.parent != parent
            or captured.phase != self._binding.phase
            or captured.round != round
            or captured.purpose != command.purpose
            or captured.index_name != command.index_name
            or type(captured.private_body) is not bytes
            or not 0 < len(captured.private_body) <= 262144
        ):
            raise _denied()
        self._total += len(captured.private_body)
        self._captures.append(captured)
        if self._total > 16 * 1024 * 1024 or len(self._captures) > 512:
            raise _denied()
        return captured.private_body

    def _topology(self, packets: dict[str, bytes]) -> InventoryTopology:
        original = self.reader.factory.epoch.original
        info = _load(packets["cluster_info"])
        state = _load(packets["identity_state"])
        nodes = _load(packets["nodes_info"])
        counts = _object(nodes["_nodes"])
        cluster_name = info["cluster_name"]
        if (
            type(cluster_name) is not str
            or not 1 <= len(cluster_name) <= 128
            or any(ord(c) < 32 for c in cluster_name)
            or info["cluster_uuid"] != original.cluster_uuid
            or _object(info["version"])["number"] != "9.5.2"
            or nodes["cluster_name"] != cluster_name
            or set(counts) != {"total", "successful", "failed"}
            or any(
                _integer(counts[k]) != n
                for k, n in (("total", 1), ("successful", 1), ("failed", 0))
            )
            or set(_object(nodes["nodes"])) != {original.stable_node_id}
            or state["cluster_uuid"] != original.cluster_uuid
            or state["master_node"] != original.stable_node_id
            or set(_object(state["nodes"])) != {original.stable_node_id}
        ):
            raise _denied()
        node = _object(_object(nodes["nodes"])[original.stable_node_id])
        ephemeral = _identifier(_object(state["nodes"])[original.stable_node_id]["ephemeral_id"])
        milliseconds = _integer(_object(node["jvm"])["start_time_in_millis"], 1, 253402300799999)
        started = datetime.fromtimestamp(milliseconds // 1000, UTC) + timedelta(
            milliseconds=milliseconds % 1000
        )
        if self._binding.phase == "original":
            if ephemeral != original.ephemeral_id or started != original.jvm_start_at:
                raise _denied()
        elif ephemeral == original.ephemeral_id or started <= original.jvm_start_at:
            raise _denied()
        return InventoryTopology(
            original.cluster_uuid, cluster_name, original.stable_node_id, ephemeral, started
        )

    @staticmethod
    def _classification(
        state_raw: bytes, listing: DecodedIndexListing, *, strict_system: bool = False
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        state = _load(state_raw)
        indices = _object(_object(state["metadata"])["indices"])
        if set(indices) != {item.name for item in listing.indices}:
            raise _denied()
        rag: list[str] = []
        foreign: list[str] = []
        for item in listing.indices:
            row = _object(indices[item.name])
            if strict_system and (
                set(row) != {"state", "settings", "mappings", "aliases", "system"}
                or type(row["system"]) is not bool
            ):
                raise _denied()
            if row["state"] != item.state or _object(row["settings"])["index.uuid"] != item.uuid:
                raise _denied()
            mapping = _object(row["mappings"])
            if "_doc" in mapping:
                if set(mapping) != {"_doc"}:
                    raise _denied()
                mapping = _object(mapping["_doc"])
            metadata = _object(mapping.get("_meta", {}))
            (rag if "rag" in metadata or "rag_index_resource" in metadata else foreign).append(
                item.name
            )
        return tuple(rag), tuple(foreign)

    async def _pass(
        self,
        parent: ReservedCutoverAction,
        round: int,
        listing: DecodedIndexListing,
        prior_names: tuple[str, ...] | None = None,
    ) -> tuple[
        tuple[DecodedIndexInventoryEntry, ...],
        DecodedForeignInventory,
        InventoryTopology,
        dict[str, bytes],
    ]:
        # First topology sample precedes every per-index read; the second one
        # follows them. Both passes use the same complete, bracketed listing.
        entries = (
            None
            if prior_names is None
            else await self._rag_entries(parent, round, prior_names, listing)
        )
        packets = {}
        for purpose in _GLOBAL:
            packets[purpose] = await self._read(
                parent, self.reader.commands.read_cluster(purpose), round
            )
        topology = self._topology(packets)
        rag_names, foreign_names = self._classification(packets["cluster_state"], listing)
        if prior_names is not None and rag_names != prior_names:
            raise _denied()
        foreign = decode_foreign_inventory(
            packets["cluster_state"],
            packets["nodes_docs"],
            cluster_uuid=topology.cluster_uuid,
            cluster_name=topology.cluster_name,
            stable_node_id=topology.stable_node_id,
            foreign_names=foreign_names,
        )
        if entries is None:
            entries = await self._rag_entries(parent, round, rag_names, listing)
        return entries, foreign, topology, packets

    async def _rag_entries(
        self,
        parent: ReservedCutoverAction,
        round: int,
        names: tuple[str, ...],
        listing: DecodedIndexListing,
    ) -> tuple[DecodedIndexInventoryEntry, ...]:
        entries = []
        listing_by_name = {row.name: row for row in listing.indices}
        for name in names:
            metadata_raw = await self._read(
                parent, self.reader.commands.read_index(name, "metadata"), round
            )
            metadata = decode_index_metadata(name, self._binding.permissions, metadata_raw)
            if metadata.uuid != listing_by_name[name].uuid:
                raise _denied()
            total = await self._read(parent, self.reader.commands.read_index(name, "count"), round)
            provenance = await self._read(
                parent, self.reader.commands.read_provenance(metadata), round
            )
            entries.append(decode_index_counts(metadata, total, provenance))
        return tuple(entries)

    def _managed_names(self, state_raw: bytes, listing: DecodedIndexListing) -> tuple[str, ...]:
        rag, _ = self._classification(state_raw, listing, strict_system=True)
        if self._unmanaged is None:
            raise _denied()
        excluded = {e.name: e.uuid for e in self._unmanaged.entries}
        rows = {e.name: e.uuid for e in listing.indices}
        managed: list[str] = []
        for name in rag:
            if name in excluded:
                if rows[name] != excluded[name]:
                    raise _denied()
                continue
            self._binding.permissions.authorize("collector", "get", (name,))
            managed.append(name)
        if set(excluded) != set(rag) - set(managed):
            raise _denied()
        return tuple(managed)

    @staticmethod
    def _join_managed_global_metadata(
        state_raw: bytes, entries: tuple[DecodedIndexInventoryEntry, ...]
    ) -> None:
        """Join each managed packet to its own complete global sample.

        Defaults exist only in the per-index packet. Global list-form aliases
        expose names only; dict-form aliases must also preserve their options.
        """
        indices = _object(_object(_load(state_raw)["metadata"])["indices"])
        for entry in entries:
            name = entry.observation.name
            row = _object(indices[name])
            metadata = _object(_load(entry.private_metadata)[name])
            mapping = _object(row["mappings"])
            if "_doc" in mapping:
                if set(mapping) != {"_doc"}:
                    raise _denied()
                mapping = _object(mapping["_doc"])
            if _canonical(_object(row["settings"])) != _canonical(
                _object(metadata["settings"])
            ) or _canonical(mapping) != _canonical(_object(metadata["mappings"])):
                raise _denied()
            aliases = row["aliases"]
            index_aliases = _object(metadata["aliases"])
            if type(aliases) is dict:
                if _canonical(aliases) != _canonical(index_aliases):
                    raise _denied()
            elif type(aliases) is list:
                if (
                    any(type(alias) is not str for alias in aliases)
                    or len(set(aliases)) != len(aliases)
                    or set(aliases) != set(index_aliases)
                ):
                    raise _denied()
            else:
                raise _denied()

    async def _physical_pass(
        self,
        parent: ReservedCutoverAction,
        round: int,
        listing: DecodedIndexListing,
        prior_names: tuple[str, ...] | None,
    ) -> _PhysicalPass:
        entries = (
            None
            if prior_names is None
            else await self._rag_entries(parent, round, prior_names, listing)
        )
        packets = {}
        for purpose in _GLOBAL:
            packets[purpose] = await self._read(
                parent, self.reader.commands.read_cluster(purpose), round
            )
        topology = self._topology(packets)
        names = self._managed_names(packets["cluster_state"], listing)
        if prior_names is not None and names != prior_names or self._unmanaged is None:
            raise _denied()
        unmanaged = decode_unmanaged_inventory(
            packets["cluster_state"],
            packets["nodes_docs"],
            cluster_uuid=topology.cluster_uuid,
            cluster_name=topology.cluster_name,
            stable_node_id=topology.stable_node_id,
            unmanaged_entries=self._unmanaged.entries,
        )
        if entries is None:
            entries = await self._rag_entries(parent, round, names, listing)
        self._join_managed_global_metadata(packets["cluster_state"], entries)
        return entries, unmanaged, topology, packets

    def _physical_signature(self, value: CapturedPhysicalInventory) -> object:
        if (
            type(value.nonce) is not UUID
            or type(value.phase) is not str
            or type(value.parent) is not ReservedCutoverAction
            or value.parent_action_id != self._binding.parent_action_id
            or value.phase != self._binding.phase
            or value.namespace_source is not self.namespace_source
            or value.namespace is not self.namespace
            or value.unmanaged_source is not self._unmanaged
            or type(value.captures) is not tuple
            or len(value.listings) != 3
            or len(value.unmanaged_passes) != 2
            or tuple(p for p, _ in value.first_packets) != _GLOBAL
            or tuple(p for p, _ in value.last_packets) != _GLOBAL
        ):
            raise _denied()
        for entry in value.rag_entries:
            _integer(entry.observation.count)
        for sample in value.unmanaged_passes:
            for unmanaged_entry in sample.entries:
                _integer(unmanaged_entry.count)
        return (
            str(value.nonce),
            _frozen(value.parent),
            value.phase,
            _frozen(value.topology),
            _frozen(value.listings),
            _frozen(value.first_packets),
            _frozen(value.last_packets),
            _frozen(value.rag_entries),
            _frozen(value.unmanaged_passes),
            tuple(id(c) for c in value.captures),
            id(value.namespace_source),
            _frozen(value.namespace),
            _frozen(value.unmanaged_source),
        )

    async def capture_physical(self, parent: ReservedCutoverAction) -> CapturedPhysicalInventory:
        try:
            self._owned()
            if (
                self._attempted
                or self.namespace_source is None
                or self.namespace is None
                or self._unmanaged is None
                or type(parent) is not ReservedCutoverAction
                or parent.action_id != self._binding.parent_action_id
            ):
                raise _denied()
            self._attempted = True
            await self.reader.revalidate(parent)
            self._owned()
            listings: list[DecodedIndexListing] = []
            passes: list[_PhysicalPass] = []
            for round in (1, 2, 3):
                listing = decode_index_listing(
                    await self._read(parent, self.reader.commands.read_cluster("listing"), round)
                )
                if (
                    len(listing.indices) > 64
                    or listing.cluster_uuid != self.reader.factory.epoch.original.cluster_uuid
                ):
                    raise _denied()
                listings.append(listing)
                if listing != listings[0]:
                    raise _denied()
                if round < 3:
                    prior = None if not passes else tuple(e.observation.name for e in passes[0][0])
                    passes.append(await self._physical_pass(parent, round, listing, prior))
            first, last = passes
            if first[2] != last[2] or _canonical(
                _load(first[3]["cluster_state"])["metadata"]
            ) != _canonical(_load(last[3]["cluster_state"])["metadata"]):
                raise _denied()
            require_same_private_inventory(first[0], last[0])
            require_same_unmanaged_entries(first[1], last[1])
            if first[1].private_physical_inventory != last[1].private_physical_inventory:
                raise _denied()
            await self.reader.revalidate(parent)
            self._owned()
            result = CapturedPhysicalInventory(
                uuid4(),
                parent,
                self._binding.phase,
                last[2],
                tuple(listings),
                tuple(first[3].items()),
                tuple(last[3].items()),
                last[0],
                (first[1], last[1]),
                tuple(self._captures),
                self.namespace_source,
                self.namespace,
                self._unmanaged,
            )
            signature = self._physical_signature(result)
            self._physical[result] = signature
            return result
        except Exception:
            raise _denied() from None

    def assert_physical_issued(self, value: object) -> None:
        try:
            self._owned()
            if (
                type(value) is not CapturedPhysicalInventory
                or value not in self._physical
                or self._physical[value] != self._physical_signature(value)
            ):
                raise _denied()
            for capture in value.captures:
                _none(self.reader.assert_issued, capture)
        except Exception:
            raise _denied() from None

    async def complete_original(
        self, parent: ReservedCutoverAction, physical: CapturedPhysicalInventory
    ) -> CapturedIndexInventory:
        try:
            self.assert_physical_issued(physical)
            if (
                self._completion_attempted
                or self._binding.phase != "original"
                or parent is not physical.parent
                or parent.kind != CutoverActionKind.STOP_OLD
            ):
                raise _denied()
            self._completion_attempted = True
            await self.reader.revalidate(parent)
            self.assert_physical_issued(physical)
            first, last = dict(physical.first_packets), dict(physical.last_packets)
            for packets in (first, last):
                if any(
                    row["system"] is not False
                    for row in _load(packets["cluster_state"])["metadata"]["indices"].values()
                ):
                    raise _denied()
            selected = {e.observation.name for e in physical.rag_entries} | {
                e.name for e in physical.unmanaged_passes[1].entries
            }
            foreign_names = tuple(
                e.name for e in physical.listings[0].indices if e.name not in selected
            )

            def foreign(packets: dict[str, bytes]) -> DecodedForeignInventory:
                return decode_foreign_inventory(
                    packets["cluster_state"],
                    packets["nodes_docs"],
                    cluster_uuid=physical.topology.cluster_uuid,
                    cluster_name=physical.topology.cluster_name,
                    stable_node_id=physical.topology.stable_node_id,
                    foreign_names=foreign_names,
                )

            before, after = foreign(first), foreign(last)
            require_same_private_foreign_inventory(before, after)
            if after.private_physical_inventory != physical.unmanaged_passes[
                1
            ].private_physical_inventory or len(selected) + len(after.entries) != len(
                physical.listings[0].indices
            ):
                raise _denied()
            await self.reader.revalidate(parent)
            self.assert_physical_issued(physical)
            result = CapturedIndexInventory(
                uuid4(),
                parent.action_id,
                "original",
                physical.topology,
                physical.rag_entries,
                after,
                last["cluster_info"],
                last["identity_state"],
                last["nodes_info"],
                physical.captures,
                physical,
                physical.unmanaged_passes[1],
            )
            self._issued[result] = self._signature(result)
            return result
        except Exception:
            raise _denied() from None

    def _secure_guard(
        self,
        parent: ReservedCutoverAction,
        physical: CapturedPhysicalInventory,
        issuer: "NativeSecurityInventory",
        cap: "MainSecurityCompletion",
    ) -> None:
        from ai_workshop.labs.rag.indexing.access_epoch_security_inventory_native import (
            MainSecurityCompletion,
            NativeSecurityInventory,
        )

        self.assert_physical_issued(physical)
        if type(issuer) is not NativeSecurityInventory or type(cap) is not MainSecurityCompletion:
            raise _denied()
        context = issuer.context
        if (
            context.security_inventory_issuer is not issuer
            or type(parent) is not ReservedCutoverAction
            or parent is not physical.parent
            or cap.parent is not parent
            or cap.physical is not physical
            or cap.source_origin.collector is not self
            or type(cap.phase) is not str
            or cap.phase != physical.phase
            or cap.phase != self._binding.phase
            or cap.phase not in {"bootstrap", "final"}
            or context._collectors.get(cap.phase) is not self
            or cap.foreign.private_physical_inventory
            != physical.unmanaged_passes[1].private_physical_inventory
        ):
            raise _denied()
        expected = (
            CutoverActionKind.STOP_BOOTSTRAP
            if cap.phase == "bootstrap"
            else CutoverActionKind.VERIFY_ACCESS
        )
        if type(parent.kind) is not CutoverActionKind or parent.kind is not expected:
            raise _denied()
        _none(issuer.assert_issued, cap)
        selected = [e.observation.name for e in physical.rag_entries]
        selected += [e.name for e in physical.unmanaged_passes[1].entries]
        selected += [e.name for e in cap.foreign.entries]
        selected += [cap.security.name]
        if len(set(selected)) != len(selected) or set(selected) != {
            e.name for e in physical.listings[0].indices
        }:
            raise _denied()

    async def complete_secure(
        self,
        parent: ReservedCutoverAction,
        physical: CapturedPhysicalInventory,
        issuer: "NativeSecurityInventory",
        cap: "MainSecurityCompletion",
    ) -> CapturedIndexInventory:
        """Complete only the context-owned native security transition; no helper I/O."""
        result: CapturedIndexInventory | None = None
        try:
            if self._completion_attempted:
                raise _denied()
            self._completion_attempted = True
            self.assert_physical_issued(physical)
            if self._binding.phase not in {"bootstrap", "final"}:
                raise _denied()
            self._secure_guard(parent, physical, issuer, cap)
            await self.reader.revalidate(parent)
            self._secure_guard(parent, physical, issuer, cap)
            last = dict(physical.last_packets)
            result = CapturedIndexInventory(
                uuid4(),
                parent.action_id,
                cap.phase,
                physical.topology,
                physical.rag_entries,
                cap.foreign,
                last["cluster_info"],
                last["identity_state"],
                last["nodes_info"],
                physical.captures,
                physical,
                physical.unmanaged_passes[1],
            )
            await self.reader.revalidate(parent)
            self._secure_guard(parent, physical, issuer, cap)
            self._secure[result] = (issuer, cap)
            self._secure_signatures[result] = (id(issuer), id(cap), id(physical))
            self._issued[result] = self._signature(result)
            self.assert_issued(result)
            return result
        except BaseException as error:
            if result is not None:
                self._secure.pop(result, None)
                self._secure_signatures.pop(result, None)
                self._issued.pop(result, None)
            if isinstance(error, Exception):
                raise _denied() from None
            raise

    @staticmethod
    def _signature(value: CapturedIndexInventory) -> tuple[object, ...]:
        t = value.topology
        for entry in value.rag_entries:
            _integer(entry.observation.count)
        for foreign_entry in value.foreign.entries:
            _integer(foreign_entry.observation.count)
        return (
            str(value.nonce),
            str(value.parent_action_id),
            value.phase,
            (
                t.cluster_uuid,
                t.cluster_name,
                t.stable_node_id,
                t.ephemeral_id,
                t.jvm_start_at.isoformat(),
            ),
            tuple(
                (
                    e.observation.name,
                    e.observation.uuid,
                    e.observation.count,
                    e.observation.settings_sha256,
                    e.observation.provenance_sha256,
                    e.private_metadata,
                )
                for e in value.rag_entries
            ),
            value.foreign.private_physical_inventory,
            (value.foreign.cluster_uuid, value.foreign.cluster_name, value.foreign.stable_node_id),
            tuple(
                (
                    e.name,
                    e.observation.uuid,
                    e.observation.schema,
                    e.observation.count_kind,
                    e.observation.count,
                    e.observation.settings_sha256,
                    e.observation.cardinality_sha256,
                    e.private_metadata,
                )
                for e in value.foreign.entries
            ),
            value.cluster_bytes,
            value.identity_bytes,
            value.nodes_bytes,
            tuple(id(c) for c in value.captures),
            id(value.physical),
            _frozen(value.unmanaged),
            _frozen(value.topology) if value.physical is not None else None,
            _frozen(value.rag_entries) if value.physical is not None else None,
            _frozen(value.foreign) if value.physical is not None else None,
            _frozen(value.phase) if value.physical is not None else None,
        )

    async def collect(self, parent: ReservedCutoverAction) -> CapturedIndexInventory:
        if self.namespace_source is not None:
            if self._binding.phase != "original":
                raise _denied()
            return await self.complete_original(parent, await self.capture_physical(parent))
        try:
            self._owned()
            if (
                self._binding.phase != "original"
                or self._attempted
                or parent.action_id != self._binding.parent_action_id
            ):
                raise _denied()
            self._attempted = True
            listings = []
            passes: list[_InventoryPass] = []
            for round in (1, 2, 3):
                listing = decode_index_listing(
                    await self._read(parent, self.reader.commands.read_cluster("listing"), round)
                )
                if (
                    len(listing.indices) > 64
                    or listing.cluster_uuid != self.reader.factory.epoch.original.cluster_uuid
                ):
                    raise _denied()
                listings.append(listing)
                if listing != listings[0]:
                    raise _denied()
                if round < 3:
                    prior_names = (
                        None if not passes else tuple(e.observation.name for e in passes[0][0])
                    )
                    passes.append(await self._pass(parent, round, listing, prior_names))
            first, last = passes
            if first[2] != last[2]:
                raise _denied()
            if _canonical(_load(first[3]["cluster_state"])["metadata"]) != _canonical(
                _load(last[3]["cluster_state"])["metadata"]
            ):
                raise _denied()
            require_same_private_inventory(first[0], last[0])
            require_same_private_foreign_inventory(first[1], last[1])
            await self.reader.revalidate(parent)
            self._owned()
            result = CapturedIndexInventory(
                uuid4(),
                parent.action_id,
                self._binding.phase,
                last[2],
                last[0],
                last[1],
                last[3]["cluster_info"],
                last[3]["identity_state"],
                last[3]["nodes_info"],
                tuple(self._captures),
            )
            self._issued[result] = self._signature(result)
            return result
        except Exception:
            raise _denied() from None

    def assert_issued(self, value: CapturedIndexInventory) -> None:
        try:
            self._owned()
            if type(value) is not CapturedIndexInventory or self._issued.get(
                value
            ) != self._signature(value):
                raise _denied()
            for capture in value.captures:
                _none(self.reader.assert_issued, capture)
            if value.physical is not None:
                self.assert_physical_issued(value.physical)
                if value.unmanaged is not value.physical.unmanaged_passes[1]:
                    raise _denied()
            if value.phase in {"bootstrap", "final"}:
                if value.physical is None or value not in self._secure:
                    raise _denied()
                issuer, cap = self._secure[value]
                if (
                    self._secure_signatures.get(value) != (id(issuer), id(cap), id(value.physical))
                    or value.foreign is not cap.foreign
                ):
                    raise _denied()
                self._secure_guard(value.physical.parent, value.physical, issuer, cap)
            elif value in self._secure or value in self._secure_signatures:
                raise _denied()
        except Exception:
            raise _denied() from None
