"""Issue only a bounded historical prerequisite for one held original epoch.

Source rederivation is the fixed internal reader's responsibility. A recipe file,
DTO, process listing, or this history ticket does not authorize a native action.
"""

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

from ai_workshop.labs.rag.indexing.access_epoch_process import ReservationReadPort
from ai_workshop.labs.rag.indexing.access_epoch_repository import original_facts
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    OriginalDeploymentIdentity,
    OriginalTargetOrigin,
    PreparedAccessEpoch,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import AliasOperationSnapshot

_CATEGORIES = frozenset(
    {"original_docker", "application", "collector", "readonly", "static_metadata"}
)
_DISPOSITIONS = frozenset(
    {
        "original_terminal",
        "collector_refused",
        "application_terminal",
        "application_failed",
        "non_control",
    }
)


class HistoryReceiptReaderPort(Protocol):
    def read_original(self) -> object: ...
    def assert_issued(self, facts: object) -> object: ...
    def assert_original(
        self, facts: object, original: OriginalDeploymentIdentity, origin: OriginalTargetOrigin
    ) -> object: ...
    def private_packet(self, facts: object) -> bytes: ...
    def sanitized_manifest(self, facts: object) -> dict[str, object]: ...


class OriginalIdentityPort(Protocol):
    @property
    def original_origin(self) -> OriginalTargetOrigin | None: ...
    async def observe_original(
        self, snapshot: AliasOperationSnapshot
    ) -> OriginalDeploymentIdentity: ...


@dataclass(frozen=True, slots=True, eq=False)
class VerifiedHistoricalControls:
    manifest_json: str


def _denied() -> ValueError:
    return ValueError("cutover_historical_controls_denied")


def _manifest(value: dict[str, object]) -> None:
    fixed = {
        "schema_version": 1,
        "scope": "bounded_original_recorded_controls",
        "coverage": "bounded_recorded_sources",
        "startup_initiator": "unrecorded_observed_start",
        "unresolved_accepted_controls": 0,
    }
    if type(value) is not dict or set(value) != set(fixed) | {"categories", "dispositions"}:
        raise _denied()
    for key, expected in fixed.items():
        if type(value[key]) is not type(expected) or value[key] != expected:
            raise _denied()
    totals = []
    for key, allowed in (("categories", _CATEGORIES), ("dispositions", _DISPOSITIONS)):
        counts = value[key]
        if (
            type(counts) is not dict
            or not counts
            or not set(counts) <= allowed
            or any(type(count) is not int or not 0 <= count <= 100000 for count in counts.values())
        ):
            raise _denied()
        totals.append(sum(counts.values()))
    if totals[0] != totals[1]:
        raise _denied()


class OriginalHistoryGate:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        reader: HistoryReceiptReaderPort,
        identity: OriginalIdentityPort,
    ) -> None:
        self.epoch, self.repository, self.journal = epoch, repository, journal
        self.reader, self.identity = reader, identity
        self._attempted = False
        self._issued: dict[VerifiedHistoricalControls, str] = {}

    def _owned(self) -> None:
        self.journal.lock.assert_owned(self.journal.owner)
        if (
            self.epoch.binding.execution_id != str(self.journal.owner.execution_id)
            or hashlib.sha256(
                json.dumps(
                    [
                        self.epoch.original.daemon_sha256,
                        "ai-workshop",
                    ]
                ).encode()
            ).hexdigest()
            != self.journal.lock.scope_sha256
        ):
            raise _denied()

    async def _readback(self) -> None:
        self._owned()
        state = await self.repository.readback(self.epoch.binding.claim)
        self._owned()
        if (
            state.prepared != self.epoch
            or state.executor_generation != self.journal.owner.executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
        ):
            raise _denied()

    async def _identity(self) -> OriginalTargetOrigin:
        self._owned()
        value = await self.identity.observe_original(self.epoch.binding.claim.snapshot)
        self._owned()
        if type(value) is not OriginalDeploymentIdentity or value != self.epoch.original:
            raise _denied()
        origin = self.identity.original_origin
        if type(origin) is not OriginalTargetOrigin or (
            origin.container_id != value.container_id or origin.daemon_sha256 != value.daemon_sha256
        ):
            raise _denied()
        return origin

    async def verify(self) -> VerifiedHistoricalControls:
        try:
            if self._attempted:
                raise _denied()
            self._attempted = True
            await self._readback()
            origin = await self._identity()
            facts = self.reader.read_original()
            self._owned()
            if self.reader.assert_issued(facts) is not None:
                raise _denied()
            if self.reader.assert_original(facts, self.epoch.original, origin) is not None:
                raise _denied()
            summary = self.reader.sanitized_manifest(facts)
            _manifest(summary)
            packet = self.reader.private_packet(facts)
            if type(packet) is not bytes or not 0 < len(packet) <= 16 * 1024 * 1024:
                raise _denied()
            self._owned()
            final_origin = await self._identity()
            if final_origin != origin:
                raise _denied()
            if self.reader.assert_original(facts, self.epoch.original, final_origin) is not None:
                raise _denied()
            await self._readback()
            claim = self.epoch.binding.claim
            manifest = canonical_json(
                {
                    "schema_version": 1,
                    "history": summary,
                    "request_id": str(claim.request_id),
                    "actor_id": str(claim.actor_id),
                    "operation_id": str(claim.snapshot.operation_id),
                    "gate_revision": claim.revision,
                    "snapshot_sha256": claim.snapshot.sha256,
                    "access_epoch_id": self.epoch.binding.access_epoch_id,
                    "execution_id": self.epoch.binding.execution_id,
                    "executor_generation": self.journal.owner.executor_generation,
                    "scope_sha256": self.journal.lock.scope_sha256,
                    "original": original_facts(self.epoch.original),
                }
            )
            payload = canonical_json(
                {
                    "schema_version": 1,
                    "manifest_json": manifest,
                    "lock_session_id": str(self.journal.owner.session_id),
                    "receipt_packet": base64.b64encode(packet).decode("ascii"),
                }
            ).encode()
            path = str(
                self.journal.root
                / ".local-data/access-epoch/private/control"
                / self.epoch.binding.execution_id
                / "historical-controls.dpapi"
            )
            self._owned()
            previous = self.journal.files.read(path)
            self._owned()
            if previous is None:
                encrypted = self.journal.protection.protect(payload)
                self._owned()
                self.journal.files.write(path, encrypted)
            elif self.journal.protection.unprotect(previous) != payload:
                raise _denied()
            self._owned()
            check = self.journal.files.read(path)
            self._owned()
            if check is None or self.journal.protection.unprotect(check) != payload:
                raise _denied()
            self._owned()
            await self._readback()
            ticket = VerifiedHistoricalControls(manifest)
            self._issued[ticket] = manifest
            return ticket
        except Exception:
            raise _denied() from None

    async def assert_verified(self, ticket: VerifiedHistoricalControls) -> None:
        try:
            self._owned()
            if (
                type(ticket) is not VerifiedHistoricalControls
                or self._issued.get(ticket) != ticket.manifest_json
            ):
                raise _denied()
            await self._readback()
        except Exception:
            raise _denied() from None
