"""Reserved local TLS file preparation; never a process or daemon settlement.

Fresh generation requires the live one-shot ticket and committed pending action.
Recovery only reads complete existing material; absence never permits regeneration.
"""

import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from ipaddress import IPv4Address
from pathlib import Path
from typing import Any
from uuid import UUID

from ai_workshop.infrastructure.local.tls_bundle import (
    ProjectTlsBundle,
    ProjectTlsBundles,
    TlsLayer,
)
from ai_workshop.labs.rag.indexing.access_epoch_process import ReservationReadPort
from ai_workshop.labs.rag.indexing.access_epoch_repository import AccessEpochReadback
from ai_workshop.labs.rag.indexing.access_epoch_submission import (
    FreshSubmissionTicket,
    ProtectedControlJournal,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import utc_text

_BEFORE = (
    CutoverActionKind.STOP_REGISTERED_APPS,
    CutoverActionKind.STOP_OLD,
    CutoverActionKind.RETIRE_OLD,
)
_FILES = tuple(
    f"{purpose}/{name}"
    for purpose in ("http", "transport")
    for name in ("node.key", "node.crt", "ca.crt")
)


class AccessEpochTlsError(ValueError):
    """Fixed failure only; the parent retains unknown reservation state."""


@dataclass(frozen=True, slots=True, eq=False)
class PreparedTlsAssets:
    epoch_id: UUID
    action_id: UUID
    original_ipv4: str
    bind_directory: str
    leaf_locations: tuple[str, ...]
    manifest_json: str


def _unknown() -> AccessEpochTlsError:
    return AccessEpochTlsError("tls_preparation_unknown")


class AccessEpochTls:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        bundles: ProjectTlsBundles,
        original_ipv4: str,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        try:
            address = IPv4Address(original_ipv4)
            if (
                str(address) != original_ipv4
                or address.is_loopback
                or address.is_multicast
                or address.is_link_local
                or address.is_unspecified
                or address.is_reserved
            ):
                raise _unknown()
            self.epoch, self.repository, self.journal = epoch, repository, journal
            self.bundles, self.original_ipv4, self.clock = bundles, original_ipv4, clock
            self._owner = journal.owner
            self._root = journal.root
            self._epoch_id = UUID(epoch.binding.access_epoch_id)
            if str(self._epoch_id) != epoch.binding.access_epoch_id or self._epoch_id.int == 0:
                raise _unknown()
            self._base = self._root / ".local-data/access-epoch/private/tls" / str(self._epoch_id)
            self._tickets: dict[UUID, FreshSubmissionTicket] = {}
            self._issued: set[PreparedTlsAssets] = set()
            self._owned()
        except Exception:
            raise _unknown() from None

    def _owned(self) -> None:
        self.journal.lock.assert_owned(self._owner)
        if (
            self.journal.owner is not self._owner
            or self.journal.root != self._root
            or not self._root.is_absolute()
            or self.epoch.binding.execution_id != str(self._owner.execution_id)
            or self.journal.scope != self.journal.lock.scope_sha256
            or sha256(
                json.dumps([self.epoch.original.daemon_sha256, "ai-workshop"]).encode()
            ).hexdigest()
            != self.journal.scope
        ):
            raise _unknown()

    def _target(self) -> str:
        return sha256(
            canonical_json(
                {
                    "preparation_kind": "local_files",
                    "schema_version": 1,
                    "epoch_id": str(self._epoch_id),
                    "execution_id": self.epoch.binding.execution_id,
                    "original_ipv4": self.original_ipv4,
                    "files": list(_FILES),
                    "original_deployment_sha256": self.epoch.original.deployment_sha256,
                }
            ).encode()
        ).hexdigest()

    def _state(self, state: AccessEpochReadback, action: ReservedCutoverAction | None) -> None:
        self._owned()
        if (
            state.prepared != self.epoch
            or state.executor_generation != self._owner.executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or state.phase in {None, "verified", "receipted"}
        ):
            raise _unknown()
        previous = state.actions if action is None else state.actions[:-1]
        if tuple(x.action.kind for x in previous) != _BEFORE:
            raise _unknown()
        last_event = 0
        for item in previous:
            if (
                item.outcome != "settled"
                or item.manifest_json is None
                or item.action.sequence <= last_event
                or item.event_sequence <= item.action.sequence
                or item.action.execution_id != self._owner.execution_id
                or item.action.executor_generation != self._owner.executor_generation
            ):
                raise _unknown()
            last_event = item.event_sequence
        if action is not None and (
            type(action) is not ReservedCutoverAction
            or action.kind != CutoverActionKind.PREPARE_TLS
            or action.execution_id != self._owner.execution_id
            or action.executor_generation != self._owner.executor_generation
            or action.sequence != last_event + 1
            or action.expected.preceding_sequence != last_event
            or not state.actions
            or state.actions[-1].action != action
            or state.actions[-1].outcome not in {"pending", "unknown"}
            or (
                state.actions[-1].outcome == "pending"
                and state.actions[-1].manifest_json is not None
            )
            or state.actions[-1].event_sequence < action.sequence
            or json.loads(action.expected.identity_json).get("target_sha256") != self._target()
        ):
            raise _unknown()

    async def _read_state(self, action: ReservedCutoverAction | None) -> AccessEpochReadback:
        self._owned()
        state = await self.repository.readback(self.epoch.binding.claim)
        self._state(state, action)
        return state

    async def prepare(self) -> FreshSubmissionTicket:
        try:
            state = await self._read_state(None)
            ticket = self.journal.prepare_expected(
                CutoverActionKind.PREPARE_TLS, state.actions[-1].event_sequence, self._target()
            )
            self._tickets[ticket.submission_id] = ticket
            return ticket
        except Exception:
            raise _unknown() from None

    def _read(self, path: Path) -> bytes | None:
        self._owned()
        result = self.journal.files.read(str(path))
        self._owned()
        if result is not None and type(result) is not bytes:
            raise _unknown()
        return result

    def _write(self, path: Path, content: bytes) -> None:
        self._owned()
        self.journal.files.write(str(path), content)
        self._owned()
        if self._read(path) != content:
            raise _unknown()

    def _binding(self, action: ReservedCutoverAction) -> dict[str, object]:
        return {
            "schema_version": 1,
            "preparation_kind": "local_files",
            "epoch_id": str(self._epoch_id),
            "execution_id": str(action.execution_id),
            "action_id": str(action.action_id),
            "executor_generation": action.executor_generation,
            "expected": action.expected.identity_json,
            "original_ipv4": self.original_ipv4,
        }

    def _packet(self, action: ReservedCutoverAction, bundle: ProjectTlsBundle) -> bytes:
        layers: dict[str, object] = {}
        for name, layer in (("http", bundle.http), ("transport", bundle.transport)):
            layers[name] = {
                key: base64.b64encode(getattr(layer, key)).decode("ascii")
                for key in (
                    "ca_certificate_pem",
                    "leaf_certificate_pem",
                    "leaf_private_key_pem",
                    "ca_key_protected",
                )
            }
        return canonical_json({"binding": self._binding(action), "layers": layers}).encode()

    def _unpack(self, action: ReservedCutoverAction, raw: bytes) -> ProjectTlsBundle:
        if not 0 < len(raw) <= 131072:
            raise _unknown()
        value: Any = json.loads(raw)
        if (
            type(value) is not dict
            or set(value) != {"binding", "layers"}
            or value["binding"] != self._binding(action)
            or type(value["layers"]) is not dict
            or set(value["layers"]) != {"http", "transport"}
        ):
            raise _unknown()
        layers = []
        for name in ("http", "transport"):
            fields = (
                "ca_certificate_pem",
                "leaf_certificate_pem",
                "leaf_private_key_pem",
                "ca_key_protected",
            )
            layer = value["layers"][name]
            if type(layer) is not dict or set(layer) != set(fields):
                raise _unknown()
            decoded = []
            for key in fields:
                if type(layer[key]) is not str:
                    raise _unknown()
                decoded.append(base64.b64decode(layer[key], validate=True))
            layers.append(TlsLayer(*decoded))
        bundle = ProjectTlsBundle(self._epoch_id, self.original_ipv4, layers[0], layers[1])
        # Reject duplicate fields, noncanonical base64/JSON and numeric type coercions.
        if self._packet(action, bundle) != raw:
            raise _unknown()
        return bundle

    def _assets(self, action: ReservedCutoverAction, bundle: ProjectTlsBundle) -> PreparedTlsAssets:
        self._owned()
        manifest = self.bundles.validate(bundle, self._epoch_id, self.original_ipv4, self.clock())
        files = self.bundles.materialize(
            bundle, self._epoch_id, self.original_ipv4, self.clock()
        ).files
        self._owned()
        if tuple(item.relative_path for item in files) != _FILES:
            raise _unknown()
        locations = tuple(str(self._base / "bind" / item.relative_path) for item in files)
        for path, item in zip(locations, files, strict=True):
            if self._read(Path(path)) != item.content:
                raise _unknown()
        public = {
            **self._binding(action),
            "http_ca_sha256": manifest.http_ca_pem_sha256,
            "transport_ca_sha256": manifest.transport_ca_pem_sha256,
            "http_ca_der_sha256": manifest.http_ca_der_sha256,
            "transport_ca_der_sha256": manifest.transport_ca_der_sha256,
            "http_leaf_der_sha256": manifest.http_leaf_der_sha256,
            "transport_leaf_der_sha256": manifest.transport_leaf_der_sha256,
            "not_valid_after": utc_text(manifest.not_valid_after),
            "dns_sans": ["localhost", "elasticsearch"],
            "ip_sans": ["127.0.0.1", self.original_ipv4],
        }
        result = PreparedTlsAssets(
            self._epoch_id,
            action.action_id,
            self.original_ipv4,
            str(self._base / "bind"),
            locations,
            canonical_json(public),
        )
        self._issued.add(result)
        return result

    def assert_issued(self, value: PreparedTlsAssets) -> None:
        try:
            self._owned()
            if type(value) is not PreparedTlsAssets or value not in self._issued:
                raise _unknown()
        except Exception:
            raise _unknown() from None

    async def read_settled(self, action: ReservedCutoverAction) -> PreparedTlsAssets:
        """Recheck original protected material for a later owned cutover stage.

        A settled public manifest is insufficient: the original private bundle
        and every exact bind file must still match. This never writes/generates.
        """
        from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER

        def validate(state: AccessEpochReadback) -> None:
            self._owned()
            if (
                type(action) is not ReservedCutoverAction
                or state.prepared != self.epoch
                or state.executor_generation != self._owner.executor_generation
                or state.operation_state != "open"
                or state.gate_state != "frozen"
                or state.receipt is not None
                or state.phase in {None, "verified", "receipted"}
                or len(state.actions) < len(_BEFORE) + 1
                or len(state.actions) > len(CUTOVER_ORDER)
                or tuple(x.action.kind for x in state.actions)
                != CUTOVER_ORDER[: len(state.actions)]
                or state.actions[len(_BEFORE)].action != action
                or action.kind != CutoverActionKind.PREPARE_TLS
                or json.loads(action.expected.identity_json).get("target_sha256") != self._target()
            ):
                raise _unknown()
            sequence = 0
            for index, item in enumerate(state.actions):
                if (
                    type(item.action.sequence) is not int
                    or type(item.event_sequence) is not int
                    or type(item.action.expected.preceding_sequence) is not int
                    or item.action.execution_id != self._owner.execution_id
                    or item.action.executor_generation != self._owner.executor_generation
                    or item.action.sequence != sequence + 1
                    or item.action.expected.preceding_sequence != sequence
                    or item.event_sequence < item.action.sequence
                    or item.outcome not in {"pending", "unknown", "settled"}
                    or item.outcome != "settled"
                    and index < len(state.actions) - 1
                    or index <= len(_BEFORE)
                    and item.outcome != "settled"
                    or item.outcome == "settled"
                    and (item.manifest_json is None or item.event_sequence <= item.action.sequence)
                    or item.outcome == "pending"
                    and (
                        item.event_sequence != item.action.sequence
                        or item.manifest_json is not None
                    )
                    or item.outcome == "unknown"
                    and item.event_sequence <= item.action.sequence
                ):
                    raise _unknown()
                sequence = item.event_sequence

        try:
            self._owned()
            before = await self.repository.readback(self.epoch.binding.claim)
            validate(before)
            record = self.journal.read(action)
            if (
                record is None
                or record.state not in {"intent", "unknown"}
                or record.child is not None
            ):
                raise _unknown()
            encrypted = self._read(self._base / "bundle.dpapi")
            if encrypted is None or not 0 < len(encrypted) <= 262144:
                raise _unknown()
            self._owned()
            packet = self.journal.protection.unprotect(encrypted)
            self._owned()
            if type(packet) is not bytes or packet == encrypted:
                raise _unknown()
            assets = self._assets(action, self._unpack(action, packet))
            if assets.manifest_json != before.actions[len(_BEFORE)].manifest_json:
                raise _unknown()
            after = await self.repository.readback(self.epoch.binding.claim)
            validate(after)
            if after != before:
                raise _unknown()
            return assets
        except Exception:
            raise _unknown() from None

    async def execute(
        self, action: ReservedCutoverAction, ticket: FreshSubmissionTicket
    ) -> PreparedTlsAssets:
        try:
            self._owned()
            if (
                type(ticket) is not FreshSubmissionTicket
                or self._tickets.pop(ticket.submission_id, None) is not ticket
                or action.expected != ticket.expected
            ):
                raise _unknown()
            state = await self._read_state(action)
            if (
                state.actions[-1].outcome != "pending"
                or state.actions[-1].event_sequence != action.sequence
            ):
                raise _unknown()
            # No process-created/finished transition: this is a local-files action.
            self.journal.begin(action, ticket)
            paths = (self._base / "bundle.dpapi", *(self._base / "bind" / x for x in _FILES))
            if any(self._read(path) is not None for path in paths):
                raise _unknown()
            self._owned()
            bundle = self.bundles.generate(self._epoch_id, self.original_ipv4, self.clock())
            self._owned()
            packet = self._packet(action, bundle)
            encrypted = self.journal.protection.protect(packet)
            self._owned()
            if type(encrypted) is not bytes or not encrypted or encrypted == packet:
                raise _unknown()
            self._write(self._base / "bundle.dpapi", encrypted)
            material = self.bundles.materialize(
                bundle, self._epoch_id, self.original_ipv4, self.clock()
            )
            self._owned()
            if tuple(item.relative_path for item in material.files) != _FILES:
                raise _unknown()
            for item in material.files:
                self._write(self._base / "bind" / item.relative_path, item.content)
            return await self.reconcile(action)
        except Exception:
            raise _unknown() from None

    async def reconcile(self, action: ReservedCutoverAction) -> PreparedTlsAssets:
        try:
            await self._read_state(action)
            record = self.journal.read(action)
            if (
                record is None
                or record.state not in {"intent", "unknown"}
                or record.child is not None
            ):
                raise _unknown()
            encrypted = self._read(self._base / "bundle.dpapi")
            if encrypted is None or not 0 < len(encrypted) <= 262144:
                raise _unknown()
            self._owned()
            packet = self.journal.protection.unprotect(encrypted)
            self._owned()
            if type(packet) is not bytes or packet == encrypted:
                raise _unknown()
            assets = self._assets(action, self._unpack(action, packet))
            await self._read_state(action)
            self._owned()
            return assets
        except Exception:
            raise _unknown() from None
