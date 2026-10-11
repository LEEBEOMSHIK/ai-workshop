"""Recorded retirement of an independently approved original application group.

The protected records describe existing process handles, never created Job
children. This bridge does not select targets, settle DB actions or reopen an
unknown target. The concrete allowlist issuer owns source authorization.
"""

import hashlib
import json
import re
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid4

from ai_workshop.infrastructure.local.process_retirement_windows import (
    RETIREMENT_EXIT_CODE,
    ProcessLifetime,
    WindowsProcessRetirement,
)
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_process import ReservationReadPort
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
)

PROJECT_ROOT = Path(__file__).absolute().parents[6]
_ORDER = ("api_supervisor", "api_launcher", "api")
_ROLES = frozenset((*_ORDER, "worker", "beat"))


def _denied() -> ValueError:
    return ValueError("app_retirement_denied")


@dataclass(frozen=True, slots=True, eq=False)
class AppRetirementAllowlist:
    nonce: UUID
    source_binding: UUID
    targets: tuple[tuple[str, ProcessLifetime], ...] = field(repr=False)
    off_roles: tuple[str, ...]


class AppRetirementAllowlistIssuer(Protocol):
    async def read_current(self) -> AppRetirementAllowlist: ...
    def assert_issued(self, allowlist: AppRetirementAllowlist) -> None: ...


@dataclass(frozen=True, slots=True, eq=False)
class FreshAppRetirementTicket:
    execution_id: UUID
    executor_generation: str
    sequence: int
    nonce: UUID
    expected: ControlExpectedIdentity
    allowlist: AppRetirementAllowlist = field(repr=False)
    kind: CutoverActionKind = field(default=CutoverActionKind.STOP_REGISTERED_APPS, init=False)


@dataclass(frozen=True, slots=True, eq=False)
class AppRetirementObservation:
    action_id: UUID
    execution_id: UUID
    executor_generation: str
    manifest_json: str


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise _denied()
        result[key] = value
    return result


def _same(left: object, right: dict[str, object]) -> bool:
    return type(left) is dict and canonical_json(left) == canonical_json(right)


class RecordedAppRetirement:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        issuer: AppRetirementAllowlistIssuer,
        native: WindowsProcessRetirement,
    ) -> None:
        self.epoch, self.repository, self.journal, self.issuer, self.native = (
            epoch,
            repository,
            journal,
            issuer,
            native,
        )
        self._tickets: dict[UUID, FreshAppRetirementTicket] = {}
        self._prepared = False
        self._observed: dict[AppRetirementObservation, str] = {}
        try:
            self._owned()
        except Exception:
            raise _denied() from None

    def _owned(self, allowlist: AppRetirementAllowlist | None = None) -> None:
        self.journal.lock.assert_owned(self.journal.owner)
        if (
            self.journal.root != PROJECT_ROOT
            or self.journal.scope != self.journal.lock.scope_sha256
            or self.epoch.binding.execution_id != str(self.journal.owner.execution_id)
            or hashlib.sha256(
                json.dumps([self.epoch.original.daemon_sha256, "ai-workshop"]).encode()
            ).hexdigest()
            != self.journal.lock.scope_sha256
        ):
            raise _denied()
        if allowlist is not None:
            self._allowlist(allowlist)
        self.journal.lock.assert_owned(self.journal.owner)

    def _allowlist(self, value: AppRetirementAllowlist) -> None:
        if (
            type(value) is not AppRetirementAllowlist
            or type(value.nonce) is not UUID
            or value.nonce.int == 0
            or type(value.source_binding) is not UUID
            or value.source_binding.int == 0
            or type(value.targets) is not tuple
            or type(value.off_roles) is not tuple
            or any(type(x) is not str for x in value.off_roles)
            or len(set(value.off_roles)) != len(value.off_roles)
        ):
            raise _denied()
        self.issuer.assert_issued(value)
        roles: set[str] = set()
        pids: set[int] = set()
        for entry in value.targets:
            if type(entry) is not tuple or len(entry) != 2:
                raise _denied()
            role, lifetime = entry
            if (
                type(role) is not str
                or role not in _ORDER
                or role in roles
                or type(lifetime) is not ProcessLifetime
                or type(lifetime.pid) is not int
                or not 0 < lifetime.pid <= 0xFFFFFFFF
                or lifetime.pid in pids
                or type(lifetime.creation_time) is not str
                or re.fullmatch(r"[1-9][0-9]{0,19}", lifetime.creation_time) is None
                or int(lifetime.creation_time) > 0xFFFFFFFFFFFFFFFF
                or not isinstance(lifetime.executable, Path)
            ):
                raise _denied()
            roles.add(role)
            pids.add(lifetime.pid)
        if not (
            roles == set(_ORDER)
            and set(value.off_roles) == {"worker", "beat"}
            or not roles
            and set(value.off_roles) == _ROLES
        ):
            raise _denied()

    @staticmethod
    def _targets(value: AppRetirementAllowlist) -> tuple[tuple[str, ProcessLifetime], ...]:
        selected = dict(value.targets)
        return tuple((role, selected[role]) for role in _ORDER if role in selected)

    def _public_allowlist(self, value: AppRetirementAllowlist) -> dict[str, object]:
        return {
            "nonce": str(value.nonce),
            "source_binding": str(value.source_binding),
            "off_roles": sorted(value.off_roles),
            "targets": [
                {"role": role, "pid": lifetime.pid, "creation_time": lifetime.creation_time}
                for role, lifetime in self._targets(value)
            ],
        }

    def _expected(self, allowlist: AppRetirementAllowlist, nonce: UUID) -> ControlExpectedIdentity:
        claim = self.epoch.binding.claim
        return ControlExpectedIdentity(
            canonical_json(
                {
                    "schema_version": 1,
                    "recording": "non_child_registered_apps",
                    "kind": CutoverActionKind.STOP_REGISTERED_APPS.value,
                    "intent_nonce": str(nonce),
                    "epoch_id": self.epoch.binding.access_epoch_id,
                    "execution_id": self.epoch.binding.execution_id,
                    "executor_generation": self.journal.owner.executor_generation,
                    "request_id": str(claim.request_id),
                    "actor_id": str(claim.actor_id),
                    "operation_id": str(claim.snapshot.operation_id),
                    "gate_revision": claim.revision,
                    "snapshot_sha256": claim.snapshot.sha256,
                    "scope_sha256": self.journal.scope,
                    "allowlist_sha256": hashlib.sha256(
                        canonical_json(self._public_allowlist(allowlist)).encode()
                    ).hexdigest(),
                    "preceding_sequence": 0,
                }
            ),
            0,
        )

    async def _state(
        self,
        allowlist: AppRetirementAllowlist,
        action: ReservedCutoverAction | None = None,
        *,
        recovery: bool = False,
    ) -> None:
        self._owned(allowlist)
        state = await self.repository.readback(self.epoch.binding.claim)
        self._owned(allowlist)
        if (
            state.prepared != self.epoch
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or state.executor_generation != self.journal.owner.executor_generation
            or state.phase in {None, "verified", "receipted"}
            or CUTOVER_ORDER[0] != CutoverActionKind.STOP_REGISTERED_APPS
        ):
            raise _denied()
        if action is None:
            if state.actions:
                raise _denied()
            return
        if (
            type(action) is not ReservedCutoverAction
            or type(action.action_id) is not UUID
            or action.action_id.int == 0
            or type(action.kind) is not CutoverActionKind
            or action.kind != CutoverActionKind.STOP_REGISTERED_APPS
            or action.execution_id != self.journal.owner.execution_id
            or action.executor_generation != self.journal.owner.executor_generation
            or type(action.sequence) is not int
            or action.sequence != 1
            or type(action.expected) is not ControlExpectedIdentity
            or type(action.expected.preceding_sequence) is not int
            or len(state.actions) != 1
            or state.actions[0].action != action
            or state.actions[0].outcome not in ({"pending", "unknown"} if recovery else {"pending"})
            or type(state.actions[0].event_sequence) is not int
            or state.actions[0].event_sequence < action.sequence
            or not recovery
            and (
                state.actions[0].manifest_json is not None
                or state.actions[0].event_sequence != action.sequence
            )
        ):
            raise _denied()
        payload = json.loads(action.expected.identity_json, object_pairs_hook=_pairs)
        nonce = UUID(payload["intent_nonce"])
        if str(nonce) != payload["intent_nonce"] or action.expected != self._expected(
            allowlist, nonce
        ):
            raise _denied()

    def _path(self, role: str | None = None) -> str:
        name = "registered-app-retirement" + ("-" + role if role is not None else "") + ".dpapi"
        return str(
            PROJECT_ROOT
            / ".local-data/access-epoch/private/control"
            / self.epoch.binding.execution_id
            / name
        )

    def _read(self, path: str, allowlist: AppRetirementAllowlist) -> dict[str, Any] | None:
        self._owned(allowlist)
        cipher = self.journal.files.read(path)
        self._owned(allowlist)
        if cipher is None:
            return None
        if type(cipher) is not bytes or not 0 < len(cipher) <= 2097152:
            raise _denied()
        raw = self.journal.protection.unprotect(cipher)
        self._owned(allowlist)
        if type(raw) is not bytes or not 0 < len(raw) <= 1048576:
            raise _denied()
        value = json.loads(raw, object_pairs_hook=_pairs)
        if type(value) is not dict or canonical_json(value).encode() != raw:
            raise _denied()
        return value

    def _write(
        self,
        path: str,
        packet: dict[str, object],
        allowlist: AppRetirementAllowlist,
        previous: dict[str, object] | None = None,
    ) -> None:
        current = self._read(path, allowlist)
        if (previous is None and current is not None) or (
            previous is not None and not _same(current, previous)
        ):
            raise _denied()
        payload = canonical_json(packet).encode()
        cipher = self.journal.protection.protect(payload)
        self._owned(allowlist)
        self.journal.files.write(path, cipher)
        self._owned(allowlist)
        if not _same(self._read(path, allowlist), packet):
            raise _denied()

    def _binding(
        self, action: ReservedCutoverAction, allowlist: AppRetirementAllowlist
    ) -> dict[str, object]:
        return {
            "action_id": str(action.action_id),
            "sequence": action.sequence,
            "expected": json.loads(action.expected.identity_json),
            "allowlist": self._public_allowlist(allowlist),
        }

    def _target(self, role: str, lifetime: ProcessLifetime) -> dict[str, object]:
        return {
            "role": role,
            "pid": lifetime.pid,
            "creation_time": lifetime.creation_time,
            "executable": str(lifetime.executable),
        }

    async def prepare(self) -> FreshAppRetirementTicket:
        try:
            self._owned()
            if self._prepared:
                raise _denied()
            self._prepared = True
            allowlist = await self.issuer.read_current()
            self._owned(allowlist)
            await self._state(allowlist)
            if self._read(self._path(), allowlist) is not None:
                raise _denied()
            nonce = uuid4()
            ticket = FreshAppRetirementTicket(
                self.journal.owner.execution_id,
                self.journal.owner.executor_generation,
                1,
                nonce,
                self._expected(allowlist, nonce),
                allowlist,
            )
            self._tickets[nonce] = ticket
            return ticket
        except Exception:
            raise _denied() from None

    def _parent(
        self,
        action: ReservedCutoverAction,
        allowlist: AppRetirementAllowlist,
        session: UUID,
        state: str,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "record_type": "registered_app_parent",
            "state": state,
            "recording_session_id": str(session),
            "binding": self._binding(action, allowlist),
            "targets": [
                self._target(role, lifetime) for role, lifetime in self._targets(allowlist)
            ],
        }

    def _target_packet(
        self, parent: dict[str, object], target: dict[str, object], state: str
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "record_type": "registered_app_target",
            "state": state,
            "recording_session_id": parent["recording_session_id"],
            "binding": parent["binding"],
            "target": target,
            "exit_code": RETIREMENT_EXIT_CODE if state == "completed" else None,
            "observation": "native_same_handle_terminal" if state == "completed" else None,
        }

    def _observe(
        self, action: ReservedCutoverAction, allowlist: AppRetirementAllowlist
    ) -> AppRetirementObservation:
        parent = self._read(self._path(), allowlist)
        if parent is None or type(parent.get("recording_session_id")) is not str:
            raise _denied()
        session = UUID(parent["recording_session_id"])
        if str(session) != parent["recording_session_id"] or not _same(
            parent, self._parent(action, allowlist, session, "completed")
        ):
            raise _denied()
        for role, lifetime in self._targets(allowlist):
            packet = self._read(self._path(role), allowlist)
            expected = self._target_packet(parent, self._target(role, lifetime), "completed")
            if not _same(packet, expected):
                raise _denied()
        manifest = canonical_json(
            {
                "schema_version": 1,
                "kind": "registered_application_lifetimes_retired",
                "action_id": str(action.action_id),
                "execution_id": str(action.execution_id),
                "executor_generation": action.executor_generation,
                "source_binding": str(allowlist.source_binding),
                "allowlist_nonce": str(allowlist.nonce),
                "target_count": len(allowlist.targets),
                "off_roles": sorted(allowlist.off_roles),
                "targets": [
                    {
                        "role": role,
                        "pid": life.pid,
                        "creation_time": life.creation_time,
                        "exit_code": RETIREMENT_EXIT_CODE,
                    }
                    for role, life in self._targets(allowlist)
                ],
            }
        )
        value = AppRetirementObservation(
            action.action_id, action.execution_id, action.executor_generation, manifest
        )
        self._observed[value] = manifest
        return value

    async def run(
        self, action: ReservedCutoverAction, ticket: FreshAppRetirementTicket
    ) -> AppRetirementObservation:
        token = None
        try:
            self._owned()
            if (
                type(ticket) is not FreshAppRetirementTicket
                or self._tickets.pop(ticket.nonce, None) is not ticket
                or type(action) is not ReservedCutoverAction
                or action.expected != ticket.expected
                or action.sequence != ticket.sequence
                or action.kind != ticket.kind
            ):
                raise _denied()
            allowlist = ticket.allowlist
            await self._state(allowlist, action)
            parent = self._parent(action, allowlist, self.journal.owner.session_id, "intent")
            self._write(self._path(), parent, allowlist)
            for role, lifetime in self._targets(allowlist):
                intent = self._target_packet(parent, self._target(role, lifetime), "intent")
                self._write(self._path(role), intent, allowlist)
                await self._state(allowlist, action)
                token = self.native.open(lifetime)
                await self._state(allowlist, action)
                result = self.native.retire(token, 30000)
                self._owned(allowlist)
                self.native.assert_result(result)
                if (
                    result.lifetime != lifetime
                    or type(result.exit_code) is not int
                    or result.exit_code != RETIREMENT_EXIT_CODE
                ):
                    raise _denied()
                await self._state(allowlist, action)
                completed = self._target_packet(parent, self._target(role, lifetime), "completed")
                self._write(self._path(role), completed, allowlist, intent)
                closing, token = token, None
                self.native.close(closing)
                self._owned(allowlist)
            await self._state(allowlist, action)
            completed_parent = self._parent(
                action, allowlist, self.journal.owner.session_id, "completed"
            )
            self._write(self._path(), completed_parent, allowlist, parent)
            result_observation = self._observe(action, allowlist)
            await self._state(allowlist, action)
            return result_observation
        except Exception:
            raise _denied() from None
        finally:
            if token is not None:
                with suppress(BaseException):
                    self.native.close(token)

    async def recover(
        self, action: ReservedCutoverAction, allowlist: AppRetirementAllowlist
    ) -> AppRetirementObservation:
        try:
            await self._state(allowlist, action, recovery=True)
            result = self._observe(action, allowlist)
            await self._state(allowlist, action, recovery=True)
            return result
        except Exception:
            raise _denied() from None

    def assert_issued(self, value: AppRetirementObservation) -> None:
        try:
            self._owned()
            if (
                type(value) is not AppRetirementObservation
                or self._observed.get(value) != value.manifest_json
            ):
                raise _denied()
        except Exception:
            raise _denied() from None
