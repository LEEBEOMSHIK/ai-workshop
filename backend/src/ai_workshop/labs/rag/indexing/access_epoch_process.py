"""Recorded fixed original commands; local completion never settles daemon work.

Not composed into the recovery CLI. Historical controls, durable journal recovery
and the complete secured controller must be verified before original invocation.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from ai_workshop.labs.rag.indexing.access_epoch_repository import AccessEpochReadback
from ai_workshop.labs.rag.indexing.access_epoch_submission import (
    ControlProcessIdentity,
    ControlSubmissionRecord,
    FreshSubmissionTicket,
    ProtectedControlJournal,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
    CONTAINER,
    CONTEXT_ENDPOINT_DIGEST,
    DOCKER_EXE,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import FrozenAliasClaim

if TYPE_CHECKING:
    from ai_workshop.infrastructure.local.control_process_windows import WindowsControlProcess

_PIPE = "npipe:////./pipe/dockerDesktopLinuxEngine"
_SUPPORTED = frozenset({CutoverActionKind.STOP_OLD, CutoverActionKind.RETIRE_OLD})


class RecordedProcessError(ValueError):
    pass


def _denied() -> RecordedProcessError:
    return RecordedProcessError("cutover_recorded_process_denied")


class ReservationReadPort(Protocol):
    async def readback(self, claim: FrozenAliasClaim) -> AccessEpochReadback: ...


def _binary_sha() -> str:
    # No PATH lookup, symlink or command replacement via caller arguments.
    path = Path(DOCKER_EXE)
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise _denied()
    return hashlib.sha256(path.read_bytes()).hexdigest()


def original_control_target(epoch: PreparedAccessEpoch, kind: CutoverActionKind) -> str:
    if type(kind) is not CutoverActionKind or kind not in _SUPPORTED:
        raise _denied()
    return hashlib.sha256(
        canonical_json(
            {
                "binary_sha256": _binary_sha(),
                "daemon_sha256": epoch.original.daemon_sha256,
                "container_id": CONTAINER,
                "endpoint_sha256": CONTEXT_ENDPOINT_DIGEST,
                "kind": kind.value,
            }
        ).encode()
    ).hexdigest()


class RecordedOriginalControlProcess:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        native: WindowsControlProcess,
        root: Path,
    ) -> None:
        self.epoch, self.repository, self.journal = epoch, repository, journal
        self.native, self.root = native, root
        self._tickets: dict[UUID, FreshSubmissionTicket] = {}
        self._owned()

    def _owned(self) -> None:
        self.journal.lock.assert_owned(self.journal.owner)
        if (
            self.epoch.binding.execution_id != str(self.journal.owner.execution_id)
            or self.epoch.original.container_id != CONTAINER
            or self.root != self.journal.root
            or hashlib.sha256(
                json.dumps([self.epoch.original.daemon_sha256, "ai-workshop"]).encode()
            ).hexdigest()
            != self.journal.lock.scope_sha256
            or hashlib.sha256(_PIPE.encode()).hexdigest() != CONTEXT_ENDPOINT_DIGEST
        ):
            raise _denied()

    def _target(self, kind: CutoverActionKind) -> str:
        self._owned()
        return original_control_target(self.epoch, kind)

    def _validate_state(self, state: AccessEpochReadback) -> None:
        if (
            state.prepared != self.epoch
            or state.executor_generation != self.journal.owner.executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or state.phase in {None, "verified", "receipted"}
        ):
            raise _denied()
        for item in state.actions:
            if (
                item.action.execution_id != self.journal.owner.execution_id
                or item.action.executor_generation != self.journal.owner.executor_generation
            ):
                raise _denied()

    async def prepare(self, kind: CutoverActionKind) -> FreshSubmissionTicket:
        try:
            target = self._target(kind)
            state = await self.repository.readback(self.epoch.binding.claim)
            self._owned()
            self._validate_state(state)
            if any(item.outcome != "settled" for item in state.actions):
                raise _denied()
            sequence = max([0, *[item.event_sequence for item in state.actions]])
            ticket = self.journal.prepare_expected(kind, sequence, target)
            self._tickets[ticket.submission_id] = ticket
            return ticket
        except Exception:
            raise _denied() from None

    def _argv(self, kind: CutoverActionKind) -> tuple[str, ...]:
        if type(kind) is not CutoverActionKind or kind not in _SUPPORTED:
            raise _denied()
        suffix = (
            ("stop", "--time", "30", CONTAINER)
            if kind == CutoverActionKind.STOP_OLD
            else ("rm", CONTAINER)
        )
        return (DOCKER_EXE, "--host", _PIPE, *suffix)

    def _capture(self, action: ReservedCutoverAction, stdout: bytes, stderr: bytes) -> None:
        if type(stdout) is not bytes or type(stderr) is not bytes:
            raise _denied()
        # No private output or its hash in public records, exceptions or manifests.
        payload = canonical_json(
            {
                "stdout": base64.b64encode(stdout).decode("ascii"),
                "stderr": base64.b64encode(stderr).decode("ascii"),
            }
        ).encode()
        path = str(
            self.root
            / ".local-data/access-epoch/private/control"
            / str(action.execution_id)
            / f"{action.action_id}.output.dpapi"
        )
        encrypted = self.journal.protection.protect(payload)
        self._owned()
        self.journal.files.write(path, encrypted)
        self._owned()
        readback = self.journal.files.read(path)
        if readback is None or self.journal.protection.unprotect(readback) != payload:
            raise _denied()
        self._owned()

    async def run(
        self, action: ReservedCutoverAction, ticket: FreshSubmissionTicket
    ) -> ControlSubmissionRecord:
        token = None
        record = None
        try:
            self._owned()
            if (
                type(ticket) is not FreshSubmissionTicket
                or self._tickets.pop(ticket.submission_id, None) is not ticket
                or type(action) is not ReservedCutoverAction
                or action.expected != ticket.expected
                or action.kind != ticket.kind
                or action.sequence != ticket.sequence
            ):
                raise _denied()
            # A ticket only matches a NEW reservation; validate a separate committed
            # readback. Missing journal alone never authorizes an old pending action.
            state = await self.repository.readback(self.epoch.binding.claim)
            self._owned()
            self._validate_state(state)
            if not state.actions:
                raise _denied()
            latest = state.actions[-1]
            if (
                latest.action != action
                or latest.outcome != "pending"
                or latest.manifest_json is not None
                or latest.event_sequence != action.sequence
                or any(item.outcome != "settled" for item in state.actions[:-1])
            ):
                raise _denied()

            if json.loads(ticket.expected.identity_json)["target_sha256"] != self._target(
                action.kind
            ):
                raise _denied()
            record = self.journal.begin(action, ticket)
            env = {
                k: v
                for k, v in os.environ.items()
                if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT"}
            }
            self._owned()
            token = self.native.create_suspended(self._argv(action.kind), env, self.root)
            child = ControlProcessIdentity(
                token.child.pid, token.child.creation_time, token.child.job_id
            )
            record = self.journal.process_created(record, child)
            self._owned()
            self.native.resume(token)
            result = self.native.wait(token, 45000)
            self._owned()
            if (
                ControlProcessIdentity(
                    result.child.pid, result.child.creation_time, result.child.job_id
                )
                != child
            ):
                raise _denied()
            self._capture(action, result.stdout, result.stderr)
            record = self.journal.process_finished(record, child, result.exit_code)
            closing, token = token, None
            self.native.close(closing)
            self._owned()
            return record
        except BaseException as exc:
            if record is not None and record.state in {"intent", "process_created"}:
                with suppress(BaseException):
                    self.journal.unknown(record)
                # Missing/uncertain ACK remains blocked, never reissued.
            if isinstance(exc, Exception):
                raise _denied() from None
            raise
        finally:
            if token is not None:
                with suppress(BaseException):
                    self.native.close(token)
                # Own Job only. No cleanup-as-daemon-settlement claim.
