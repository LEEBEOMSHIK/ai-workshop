"""Protected recording only: no launcher, daemon settlement, or proof issuance.

A fresh in-memory ticket binds a newly prepared expected payload. It is not a
DB commit capability. Missing files and local process exit cannot justify replay.
"""

import hashlib
import json
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast
from uuid import UUID, uuid4

from ai_workshop.infrastructure.local.credential_store_windows import (
    PrivateFilePort,
    ProtectionPort,
)
from ai_workshop.infrastructure.local.cutover_control_windows import (
    HeldControlLock,
    WindowsControlLock,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    ReservedCutoverAction,
    canonical_json,
)

type RecordingState = Literal["intent", "process_created", "process_finished", "unknown"]


class SubmissionJournalError(ValueError):
    pass


def _denied() -> SubmissionJournalError:
    return SubmissionJournalError("cutover_submission_record_denied")


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hex(value: object) -> bool:
    return type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _uuid(value: object) -> UUID:
    if type(value) is not str:
        raise _denied()
    result = UUID(value)
    if str(result) != value:
        raise _denied()
    return result


def _pairs(items: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for name, value in items:
        if name in result:
            raise _denied()
        result[name] = value
    return result


@dataclass(frozen=True, slots=True)
class ControlProcessIdentity:
    pid: int
    creation_time: str
    job_id: UUID


@dataclass(frozen=True, slots=True)
class FreshSubmissionTicket:
    execution_id: UUID
    executor_generation: str
    kind: CutoverActionKind
    sequence: int
    submission_id: UUID
    expected: ControlExpectedIdentity


@dataclass(frozen=True, slots=True)
class ControlSubmissionRecord:
    action: ReservedCutoverAction
    submission_id: UUID
    scope_sha256: str
    lock_session_id: UUID
    revision: int
    state: RecordingState
    child: ControlProcessIdentity | None = None
    exit_code: int | None = None


def _child_valid(child: ControlProcessIdentity) -> bool:
    return (
        type(child) is ControlProcessIdentity
        and type(child.pid) is int
        and 0 < child.pid <= 0xFFFFFFFF
        and type(child.creation_time) is str
        and re.fullmatch(r"[1-9][0-9]{0,19}", child.creation_time) is not None
        and type(child.job_id) is UUID
    )


class ProtectedControlJournal:
    def __init__(
        self,
        root: str | Path,
        protection: ProtectionPort,
        files: PrivateFilePort,
        lock: WindowsControlLock,
        owner: HeldControlLock,
        scope_sha256: str,
    ) -> None:
        self.root = Path(root)
        self.protection, self.files, self.lock, self.owner = protection, files, lock, owner
        self.scope = scope_sha256
        self._tickets: dict[UUID, FreshSubmissionTicket] = {}
        self._issued_sequences: set[int] = set()
        self._current: dict[UUID, ControlSubmissionRecord] = {}
        self._owned()

    def _owned(self) -> None:
        try:
            self.lock.assert_owned(self.owner)
            if not _hex(self.scope) or self.lock.scope_sha256 != self.scope:
                raise _denied()
        except Exception:
            raise _denied() from None

    def _action_valid(self, action: ReservedCutoverAction) -> None:
        if (
            type(action) is not ReservedCutoverAction
            or type(action.action_id) is not UUID
            or type(action.execution_id) is not UUID
            or action.execution_id != self.owner.execution_id
            or type(action.executor_generation) is not str
            or action.executor_generation != self.owner.executor_generation
            or type(action.sequence) is not int
            or action.sequence <= 0
            or type(action.kind) is not CutoverActionKind
            or type(action.expected) is not ControlExpectedIdentity
            or type(action.expected.identity_json) is not str
            or type(action.expected.preceding_sequence) is not int
            or action.expected.preceding_sequence != action.sequence - 1
        ):
            raise _denied()

    def _path(self, action: ReservedCutoverAction) -> str:
        self._action_valid(action)
        return str(
            self.root
            / ".local-data/access-epoch/private/control"
            / str(action.execution_id)
            / f"{action.action_id}.dpapi"
        )

    def prepare_expected(
        self, kind: CutoverActionKind, preceding_sequence: int, target_sha256: str
    ) -> FreshSubmissionTicket:
        self._owned()
        if (
            type(kind) is not CutoverActionKind
            or type(preceding_sequence) is not int
            or preceding_sequence < 0
            or preceding_sequence + 1 in self._issued_sequences
            or not _hex(target_sha256)
        ):
            raise _denied()
        nonce = uuid4()
        expected = ControlExpectedIdentity(
            canonical_json(
                {
                    "schema_version": 1,
                    "submission_id": str(nonce),
                    "scope_sha256": self.scope,
                    "target_sha256": target_sha256,
                    "execution_id": str(self.owner.execution_id),
                    "executor_generation": self.owner.executor_generation,
                    "kind": kind.value,
                    "preceding_sequence": preceding_sequence,
                }
            ),
            preceding_sequence,
        )
        ticket = FreshSubmissionTicket(
            self.owner.execution_id,
            self.owner.executor_generation,
            kind,
            preceding_sequence + 1,
            nonce,
            expected,
        )
        self._issued_sequences.add(ticket.sequence)
        self._tickets[nonce] = ticket
        return ticket

    @staticmethod
    def _wire(record: ControlSubmissionRecord) -> dict[str, object]:
        action, child = record.action, record.child
        return {
            "schema_version": 1,
            "execution_id": str(action.execution_id),
            "executor_generation": action.executor_generation,
            "action_id": str(action.action_id),
            "sequence": action.sequence,
            "kind": action.kind.value,
            "expected_sha256": _digest(action.expected.identity_json),
            "submission_id": str(record.submission_id),
            "scope_sha256": record.scope_sha256,
            "lock_session_id": str(record.lock_session_id),
            "revision": record.revision,
            "state": record.state,
            "child_pid": child.pid if child else None,
            "child_creation_time": child.creation_time if child else None,
            "job_id": str(child.job_id) if child else None,
            "exit_code": record.exit_code,
        }

    def read(self, action: ReservedCutoverAction) -> ControlSubmissionRecord | None:
        self._owned()
        try:
            encrypted = self.files.read(self._path(action))
            self._owned()
            if encrypted is None:
                return None
            payload = json.loads(self.protection.unprotect(encrypted), object_pairs_hook=_pairs)
            if type(payload) is not dict:
                raise _denied()
            dummy = ControlSubmissionRecord(action, uuid4(), self.scope, uuid4(), 1, "intent")
            if set(payload) != set(self._wire(dummy)):
                raise _denied()
            reference = self._wire(dummy)
            for name in (
                "schema_version",
                "execution_id",
                "executor_generation",
                "action_id",
                "sequence",
                "kind",
                "expected_sha256",
                "scope_sha256",
            ):
                if (
                    type(payload[name]) is not type(reference[name])
                    or payload[name] != reference[name]
                ):
                    raise _denied()
            submission_id = _uuid(payload["submission_id"])
            session_id = _uuid(payload["lock_session_id"])
            expected = json.loads(action.expected.identity_json, object_pairs_hook=_pairs)
            expected_binding = {
                "schema_version": 1,
                "submission_id": str(submission_id),
                "scope_sha256": self.scope,
                "execution_id": str(action.execution_id),
                "executor_generation": action.executor_generation,
                "kind": action.kind.value,
                "preceding_sequence": action.expected.preceding_sequence,
            }
            if (
                type(expected) is not dict
                or set(expected) != set(expected_binding) | {"target_sha256"}
                or not _hex(expected["target_sha256"])
                or action.expected.identity_json != canonical_json(expected)
            ):
                raise _denied()
            for name, value in expected_binding.items():
                if type(expected[name]) is not type(value) or expected[name] != value:
                    raise _denied()
            state, revision = payload["state"], payload["revision"]
            if (
                type(state) is not str
                or state not in {"intent", "process_created", "process_finished", "unknown"}
                or type(revision) is not int
                or not 1 <= revision <= 3
            ):
                raise _denied()
            child = None
            if payload["child_pid"] is not None:
                child = ControlProcessIdentity(
                    payload["child_pid"], payload["child_creation_time"], _uuid(payload["job_id"])
                )
                if not _child_valid(child):
                    raise _denied()
            elif payload["child_creation_time"] is not None or payload["job_id"] is not None:
                raise _denied()
            exit_code = payload["exit_code"]
            if (
                state == "intent"
                and (revision != 1 or child is not None)
                or state == "process_created"
                and (revision != 2 or child is None)
                or state == "process_finished"
                and (revision != 3 or child is None)
                or state == "unknown"
                and revision != (2 if child is None else 3)
                or state != "process_finished"
                and exit_code is not None
                or state == "process_finished"
                and (type(exit_code) is not int or not -0x80000000 <= exit_code <= 0xFFFFFFFF)
            ):
                raise _denied()
            record = ControlSubmissionRecord(
                action,
                submission_id,
                self.scope,
                session_id,
                revision,
                cast(RecordingState, state),
                child,
                exit_code,
            )
            self._owned()
            return record
        except Exception:
            raise _denied() from None

    def _write(self, record: ControlSubmissionRecord) -> ControlSubmissionRecord:
        self._owned()
        try:
            encrypted = self.protection.protect(canonical_json(self._wire(record)).encode())
            self._owned()
            self.files.write(
                self._path(record.action),
                encrypted,
            )
            self._owned()
            readback = self.read(record.action)
            if readback != record:
                raise _denied()
            self._current[record.action.action_id] = record
            return record
        except Exception:
            self._current.pop(record.action.action_id, None)
            raise _denied() from None

    def begin(
        self, action: ReservedCutoverAction, ticket: FreshSubmissionTicket
    ) -> ControlSubmissionRecord:
        self._owned()
        if (
            type(ticket) is not FreshSubmissionTicket
            or self._tickets.get(ticket.submission_id) is not ticket
        ):
            raise _denied()
        # Consume before validation/I/O. Even lost write ACK never permits replay.
        del self._tickets[ticket.submission_id]
        self._action_valid(action)
        if (
            action.execution_id != ticket.execution_id
            or action.executor_generation != ticket.executor_generation
            or action.kind != ticket.kind
            or action.sequence != ticket.sequence
            or action.expected != ticket.expected
            or self.read(action) is not None
        ):
            raise _denied()
        return self._write(
            ControlSubmissionRecord(
                action, ticket.submission_id, self.scope, self.owner.session_id, 1, "intent"
            )
        )

    def _advance(
        self,
        record: ControlSubmissionRecord,
        state: RecordingState,
        child: ControlProcessIdentity | None = None,
        exit_code: int | None = None,
    ) -> ControlSubmissionRecord:
        self._owned()
        if (
            self._current.get(record.action.action_id) is not record
            or record.state in {"unknown", "process_finished"}
            or self.read(record.action) != record
        ):
            raise _denied()
        self._current.pop(record.action.action_id)
        return self._write(
            replace(
                record, state=state, revision=record.revision + 1, child=child, exit_code=exit_code
            )
        )

    def process_created(
        self, record: ControlSubmissionRecord, child: ControlProcessIdentity
    ) -> ControlSubmissionRecord:
        if record.state != "intent" or not _child_valid(child):
            raise _denied()
        return self._advance(record, "process_created", child)

    def process_finished(
        self, record: ControlSubmissionRecord, child: ControlProcessIdentity, exit_code: int
    ) -> ControlSubmissionRecord:
        if (
            record.state != "process_created"
            or not _child_valid(child)
            or child != record.child
            or type(exit_code) is not int
            or not -0x80000000 <= exit_code <= 0xFFFFFFFF
        ):
            raise _denied()
        return self._advance(record, "process_finished", child, exit_code)

    def unknown(self, record: ControlSubmissionRecord) -> ControlSubmissionRecord:
        return self._advance(record, "unknown", record.child)
