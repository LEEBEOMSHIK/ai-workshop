"""Record one fixed Compose helper after fresh committed reservation.

The returned record proves only local helper/Job completion. The authoritative
daemon, TLS, authentication and preservation observations remain separate.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from contextlib import suppress
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from ai_workshop.labs.rag.indexing import access_epoch_process as original_process
from ai_workshop.labs.rag.indexing.access_epoch_deployment import (
    PROJECT_ROOT,
    DeploymentCommands,
    RetiredPredecessor,
)
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_process import ReservationReadPort
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
    CommandExecutor,
    FixedCommand,
    ReadOnlyCommandExecutor,
)

if TYPE_CHECKING:
    from ai_workshop.infrastructure.local.control_process_windows import WindowsControlProcess

_KINDS = {CutoverActionKind.START_BOOTSTRAP, CutoverActionKind.START_SECURED}


def _denied() -> ValueError:
    return ValueError("cutover_deployment_process_denied")


class DeploymentInventoryPort(Protocol):
    async def read(self) -> tuple[bytes, bytes]: ...


class FixedDeploymentInventory:
    def __init__(self, executor: CommandExecutor) -> None:
        self.executor = ReadOnlyCommandExecutor(executor)

    async def read(self) -> tuple[bytes, bytes]:
        try:
            raw = await self.executor.run(FixedCommand.ORIGINAL_DAEMON_ID)
            value = json.loads(raw)
            if type(value) is not dict or set(value) != {"id", "os"}:
                raise _denied()
            daemon = canonical_json({"ID": value["id"], "OSType": value["os"]}).encode()
            inventory = (await self.executor.run(FixedCommand.ORIGINAL_SLOT_INVENTORY)).encode()
            if len(inventory) > 4_194_304:
                raise _denied()
            return daemon, inventory
        except Exception:
            raise _denied() from None


class RecordedDeploymentControlProcess:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        repository: ReservationReadPort,
        builder: DeploymentCommands,
        journal: ProtectedControlJournal,
        native: WindowsControlProcess,
        inventory: DeploymentInventoryPort,
    ) -> None:
        self.epoch, self.repository, self.builder = epoch, repository, builder
        self.journal, self.native, self.inventory = journal, native, inventory
        self._tickets: dict[UUID, FreshSubmissionTicket] = {}
        self._binaries: dict[UUID, str] = {}
        self._owned()

    def _owned(self) -> None:
        self.journal.lock.assert_owned(self.journal.owner)
        if (
            self.builder.epoch != self.epoch
            or self.journal.root != PROJECT_ROOT
            or self.epoch.binding.execution_id != str(self.journal.owner.execution_id)
            or hashlib.sha256(
                json.dumps([self.epoch.original.daemon_sha256, "ai-workshop"]).encode()
            ).hexdigest()
            != self.journal.lock.scope_sha256
        ):
            raise _denied()

    def _state(
        self,
        state: AccessEpochReadback,
        kind: CutoverActionKind,
        action: ReservedCutoverAction | None,
    ) -> None:
        self._owned()
        if (
            kind not in _KINDS
            or state.prepared != self.epoch
            or state.executor_generation != self.journal.owner.executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or state.phase in {None, "verified", "receipted"}
        ):
            raise _denied()
        previous = state.actions if action is None else state.actions[:-1]
        if tuple(x.action.kind for x in previous) != CUTOVER_ORDER[: CUTOVER_ORDER.index(kind)]:
            raise _denied()
        sequence = 0
        for row in previous:
            if (
                row.outcome != "settled"
                or row.manifest_json is None
                or row.action.sequence <= sequence
                or row.event_sequence <= row.action.sequence
                or row.action.execution_id != self.journal.owner.execution_id
                or row.action.executor_generation != self.journal.owner.executor_generation
            ):
                raise _denied()
            sequence = row.event_sequence
        if action is not None and (
            not state.actions
            or state.actions[-1].action != action
            or state.actions[-1].outcome != "pending"
            or state.actions[-1].event_sequence != action.sequence
            or state.actions[-1].manifest_json is not None
            or action.sequence != sequence + 1
        ):
            raise _denied()

    async def prepare(self, kind: CutoverActionKind) -> FreshSubmissionTicket:
        try:
            self._owned()
            state = await self.repository.readback(self.epoch.binding.claim)
            self._state(state, kind, None)
            ticket = self.journal.prepare_expected(
                kind, state.actions[-1].event_sequence, self.builder.target_sha256(kind)
            )
            self._tickets[ticket.submission_id] = ticket
            self._binaries[ticket.submission_id] = original_process._binary_sha()
            return ticket
        except Exception:
            raise _denied() from None

    def _capture(self, action: ReservedCutoverAction, stdout: bytes, stderr: bytes) -> None:
        if type(stdout) is not bytes or type(stderr) is not bytes:
            raise _denied()
        packet = canonical_json(
            {
                "stdout": base64.b64encode(stdout).decode(),
                "stderr": base64.b64encode(stderr).decode(),
            }
        ).encode()
        path = str(
            self.journal.root
            / ".local-data/access-epoch/private/control"
            / str(action.execution_id)
            / f"{action.action_id}.output.dpapi"
        )
        self._owned()
        if self.journal.files.read(path) is not None:
            raise _denied()
        encrypted = self.journal.protection.protect(packet)
        self._owned()
        self.journal.files.write(path, encrypted)
        self._owned()
        observed = self.journal.files.read(path)
        if observed is None or self.journal.protection.unprotect(observed) != packet:
            raise _denied()
        self._owned()

    async def run(
        self,
        action: ReservedCutoverAction,
        ticket: FreshSubmissionTicket,
        predecessor: RetiredPredecessor,
    ) -> ControlSubmissionRecord:
        record, token = None, None
        try:
            self._owned()
            binary = self._binaries.pop(ticket.submission_id, None)
            if (
                type(ticket) is not FreshSubmissionTicket
                or self._tickets.pop(ticket.submission_id, None) is not ticket
                or action.expected != ticket.expected
                or action.kind != ticket.kind
                or action.sequence != ticket.sequence
                or action.executor_generation != ticket.executor_generation
                or binary != original_process._binary_sha()
            ):
                raise _denied()
            state = await self.repository.readback(self.epoch.binding.claim)
            self._state(state, action.kind, action)
            retired = next((x for x in state.actions[:-1] if x.action == predecessor.action), None)
            if (
                retired is None
                or retired.manifest_json != predecessor.settlement.manifest_json
                or retired.observed_at != predecessor.settlement.observed_at
                or predecessor.settlement.outcome != "settled"
            ):
                raise _denied()
            daemon, inventory = await self.inventory.read()
            self._owned()
            state = await self.repository.readback(self.epoch.binding.claim)
            self._state(state, action.kind, action)
            command = self.builder.build(action, predecessor, daemon, inventory)
            self.builder.assert_issued(command)
            self._owned()
            record = self.journal.begin(action, ticket)
            env = {
                k: v
                for k, v in os.environ.items()
                if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT"}
            }
            env.update(command.environment)
            self._owned()
            if binary != original_process._binary_sha():
                raise _denied()
            token = self.native.create_suspended(command.argv, env, command.cwd)
            child = ControlProcessIdentity(
                token.child.pid, token.child.creation_time, token.child.job_id
            )
            record = self.journal.process_created(record, child)
            self._owned()
            self.native.resume(token)
            self._owned()
            result = self.native.wait(token, 60000)
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
            state = await self.repository.readback(self.epoch.binding.claim)
            self._state(state, action.kind, action)
            return record
        except BaseException as exc:
            if record is not None and record.state in {"intent", "process_created"}:
                with suppress(BaseException):
                    self.journal.unknown(record)
            if isinstance(exc, Exception):
                raise _denied() from None
            raise
        finally:
            if token is not None:
                with suppress(BaseException):
                    self.native.close(token)
