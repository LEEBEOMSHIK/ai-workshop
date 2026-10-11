"""Recorded fixed bootstrap role helpers, with clean-commit one-shot mutations.

The caller constructs this only for its verified bootstrap container. Local Job
completion proves the helper ended; authenticated HTTP decoders settle its key.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, cast
from uuid import UUID, uuid4

from ai_workshop.labs.rag.indexing import access_epoch_process as original_process
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap import BootstrapCommand, BootstrapCommands
from ai_workshop.labs.rag.indexing.access_epoch_keys import (
    KeyActionReadback,
    ReservedKeyAction,
    SqlAlchemyEpochKeyRepository,
)
from ai_workshop.labs.rag.indexing.access_epoch_process import ReservationReadPort
from ai_workshop.labs.rag.indexing.access_epoch_role_keys import PrivateBootstrapResult
from ai_workshop.labs.rag.indexing.access_epoch_submission import (
    ControlProcessIdentity,
    ProtectedControlJournal,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import CONTEXT_ENDPOINT_DIGEST

if TYPE_CHECKING:
    from ai_workshop.infrastructure.local.control_process_windows import WindowsControlProcess


def _denied() -> ValueError:
    return ValueError("cutover_bootstrap_process_denied")


class RecordedBootstrapKeyCommands:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        parent: ReservedCutoverAction,
        repository: ReservationReadPort,
        keys: SqlAlchemyEpochKeyRepository,
        builder: BootstrapCommands,
        journal: ProtectedControlJournal,
        native: WindowsControlProcess,
        root: Path,
    ) -> None:
        self.epoch, self.parent, self.repository, self.keys = epoch, parent, repository, keys
        self.builder, self.journal, self.native, self.root = builder, journal, native, root
        self._seen: set[BootstrapCommand] = set()
        self._owned()

    def _owned(self) -> None:
        self.journal.lock.assert_owned(self.journal.owner)
        if (
            self.root != self.journal.root
            or self.epoch.binding.execution_id != str(self.journal.owner.execution_id)
            or self.parent.execution_id != self.journal.owner.execution_id
            or self.parent.executor_generation != self.journal.owner.executor_generation
            or self.parent.kind != CutoverActionKind.ISSUE_ROLE_KEY
            or self.builder.binding.epoch_id != UUID(self.epoch.binding.access_epoch_id)
            or self.builder.binding.execution_id != self.parent.execution_id
            or hashlib.sha256(
                json.dumps([self.epoch.original.daemon_sha256, "ai-workshop"]).encode()
            ).hexdigest()
            != self.journal.lock.scope_sha256
        ):
            raise _denied()

    async def _state(self) -> None:
        self._owned()
        state = await self.repository.readback(self.epoch.binding.claim)
        self._owned()
        if (
            state.prepared != self.epoch
            or state.executor_generation != self.parent.executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or not state.actions
            or state.actions[-1].action != self.parent
            or state.actions[-1].outcome not in {"pending", "unknown"}
            or any(x.outcome != "settled" for x in state.actions[:-1])
        ):
            raise _denied()

    def _capture(self, action: ReservedCutoverAction, stdout: bytes, stderr: bytes) -> None:
        if type(stdout) is not bytes or type(stderr) is not bytes:
            raise _denied()
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
        self._owned()
        if self.journal.files.read(path) is not None:
            raise _denied()
        encrypted = self.journal.protection.protect(payload)
        self._owned()
        self.journal.files.write(path, encrypted)
        self._owned()
        observed = self.journal.files.read(path)
        if observed is None or self.journal.protection.unprotect(observed) != payload:
            raise _denied()
        self._owned()

    def _catalog_path(self) -> str:
        return str(
            self.root
            / ".local-data/access-epoch/private/control"
            / str(self.parent.execution_id)
            / f"{self.parent.action_id}.helpers.dpapi"
        )

    def _target(self, operation: str, role: str, issuance: str, permissions: str | None) -> str:
        return hashlib.sha256(
            canonical_json(
                {
                    "binary_sha256": original_process._binary_sha(),
                    "daemon_sha256": self.epoch.original.daemon_sha256,
                    "endpoint_sha256": CONTEXT_ENDPOINT_DIGEST,
                    "bootstrap_container_id": self.builder.binding.container_id,
                    "parent_action_id": str(self.parent.action_id),
                    "operation": operation,
                    "role": role,
                    "issuance_id": issuance,
                    "permissions_sha256": permissions,
                }
            ).encode()
        ).hexdigest()

    def _catalog(
        self, rows: tuple[KeyActionReadback, ...], *, mutation: bool
    ) -> list[dict[str, object]]:
        self._owned()
        encrypted = self.journal.files.read(self._catalog_path())
        self._owned()
        entries: list[dict[str, object]] = []
        if encrypted is not None:
            if type(encrypted) is not bytes or len(encrypted) > 2_097_152:
                raise _denied()
            raw = self.journal.protection.unprotect(encrypted)
            if type(raw) is not bytes or len(raw) > 1_048_576:
                raise _denied()
            packet = json.loads(raw)
            if (
                type(packet) is not dict
                or set(packet) != {"parent_action_id", "entries"}
                or packet["parent_action_id"] != str(self.parent.action_id)
                or type(packet["entries"]) is not list
                or len(packet["entries"]) > 256
                or canonical_json(packet).encode() != raw
            ):
                raise _denied()
            entries = packet["entries"]
        seen: set[UUID] = set()
        mutations: set[UUID] = set()
        for item in entries:
            if type(item) is not dict or set(item) != {
                "action_id",
                "sequence",
                "expected",
                "operation",
                "role",
                "issuance_id",
                "permissions_sha256",
            }:
                raise _denied()
            action_id = UUID(cast(str, item["action_id"]))
            if str(action_id) != item["action_id"] or action_id in seen:
                raise _denied()
            seen.add(action_id)
            matches = [
                x.action
                for x in rows
                if str(x.action.issuance_id) == item["issuance_id"]
                and x.action.role == item["role"]
            ]
            if not matches:
                raise _denied()
            if item["operation"] == "key_lookup":
                if (
                    item["sequence"] != self.parent.sequence
                    or item["permissions_sha256"] is not None
                ):
                    raise _denied()
            elif item["operation"] in {"issue", "invalidate"}:
                found = next((x for x in matches if x.action_id == action_id), None)
                if found is None or (found.kind, found.sequence, found.permissions_sha256) != (
                    item["operation"],
                    item["sequence"],
                    item["permissions_sha256"],
                ):
                    raise _denied()
                mutations.add(action_id)
            else:
                raise _denied()
            if type(item["sequence"]) is not int or type(item["expected"]) is not str:
                raise _denied()
            expected = json.loads(item["expected"])
            if expected.get("target_sha256") != self._target(
                item["operation"],
                cast(str, item["role"]),
                cast(str, item["issuance_id"]),
                cast(str | None, item["permissions_sha256"]),
            ):
                raise _denied()
            recorded_action = ReservedCutoverAction(
                action_id,
                self.parent.execution_id,
                item["sequence"],
                CutoverActionKind.ISSUE_ROLE_KEY,
                ControlExpectedIdentity(item["expected"], item["sequence"] - 1),
                self.parent.executor_generation,
            )
            record = self.journal.read(recorded_action)
            self._owned()
            if mutation and (record is None or record.state != "process_finished"):
                raise _denied()
        if mutation and any(x.action.action_id not in mutations for x in rows[:-1]):
            raise _denied()
        return entries

    def _record_binding(
        self,
        entries: list[dict[str, object]],
        action: ReservedCutoverAction,
        operation: str,
        command: BootstrapCommand,
        permissions: str | None,
    ) -> None:
        if len(entries) >= 256 or any(x["action_id"] == str(action.action_id) for x in entries):
            raise _denied()
        packet = canonical_json(
            {
                "parent_action_id": str(self.parent.action_id),
                "entries": [
                    *entries,
                    {
                        "action_id": str(action.action_id),
                        "sequence": action.sequence,
                        "expected": action.expected.identity_json,
                        "operation": operation,
                        "role": command.role,
                        "issuance_id": str(command.issuance_id),
                        "permissions_sha256": permissions,
                    },
                ],
            }
        ).encode()
        self._owned()
        encrypted = self.journal.protection.protect(packet)
        self._owned()
        self.journal.files.write(self._catalog_path(), encrypted)
        self._owned()
        observed = self.journal.files.read(self._catalog_path())
        if observed is None or self.journal.protection.unprotect(observed) != packet:
            raise _denied()
        self._owned()

    async def execute(
        self, command: BootstrapCommand, reservation: ReservedKeyAction | None
    ) -> PrivateBootstrapResult:
        token = None
        record = None
        journal = None
        try:
            self._owned()
            if type(command) is not BootstrapCommand or command in self._seen:
                raise _denied()
            self._seen.add(command)
            if reservation is not None:
                self.keys.consume_fresh(reservation)
            self.builder.assert_role_command(command, reservation.kind if reservation else None)
            await self._state()
            rows = await self.keys.readback(self.epoch, self.parent)
            self._owned()
            entries = self._catalog(rows, mutation=reservation is not None)
            if reservation is None:
                if not any(
                    x.action.role == command.role and x.action.issuance_id == command.issuance_id
                    for x in rows
                ):
                    raise _denied()
                action_id, sequence = uuid4(), self.parent.sequence
                operation = "key_lookup"
                permissions_sha = None
            else:
                if (
                    not rows
                    or rows[-1].action != reservation
                    or rows[-1].outcome != "pending"
                    or any(x.outcome != "settled" for x in rows[:-1])
                    or (reservation.role, reservation.issuance_id)
                    != (command.role, command.issuance_id)
                    or reservation.permissions_sha256
                    != hashlib.sha256(
                        canonical_json(
                            self.builder.permissions_descriptor(reservation.role)
                        ).encode()
                    ).hexdigest()
                ):
                    raise _denied()
                action_id, sequence = reservation.action_id, reservation.sequence
                operation = reservation.kind
                permissions_sha = reservation.permissions_sha256
            target = self._target(
                operation, cast(str, command.role), str(command.issuance_id), permissions_sha
            )
            journal = ProtectedControlJournal(
                self.root,
                self.journal.protection,
                self.journal.files,
                self.journal.lock,
                self.journal.owner,
                self.journal.lock.scope_sha256,
            )
            ticket = journal.prepare_expected(
                CutoverActionKind.ISSUE_ROLE_KEY, sequence - 1, target
            )
            action = ReservedCutoverAction(
                action_id,
                self.parent.execution_id,
                sequence,
                CutoverActionKind.ISSUE_ROLE_KEY,
                ticket.expected,
                self.parent.executor_generation,
            )
            self._record_binding(entries, action, operation, command, permissions_sha)
            record = journal.begin(action, ticket)
            env = {
                k: v
                for k, v in os.environ.items()
                if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT"}
            }
            self._owned()
            token = self.native.create_suspended(
                command.argv, env, self.root, stdin=command.private_stdin
            )
            child = ControlProcessIdentity(
                token.child.pid, token.child.creation_time, token.child.job_id
            )
            record = journal.process_created(record, child)
            self._owned()
            self.native.resume(token)
            self._owned()
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
            record = journal.process_finished(record, child, result.exit_code)
            closing, token = token, None
            self.native.close(closing)
            await self._state()
            return PrivateBootstrapResult(result.exit_code, result.stdout)
        except BaseException as exc:
            if (
                record is not None
                and journal is not None
                and record.state in {"intent", "process_created"}
            ):
                with suppress(BaseException):
                    journal.unknown(record)
            if isinstance(exc, Exception):
                raise _denied() from None
            raise
        finally:
            if token is not None:
                with suppress(BaseException):
                    self.native.close(token)
