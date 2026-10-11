"""One recorded bootstrap reset and protected credential custody, not server audit.

Recovery reads only completed, bound private captures. It never executes a reset
or treats a local helper's completion as daemon settlement or realm cleanup.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal
from uuid import UUID

from pydantic import SecretStr

from ai_workshop.labs.rag.indexing import access_epoch_process as original_process
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap import BootstrapCommand, BootstrapCommands
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_binding import BootstrapBindingFactory
from ai_workshop.labs.rag.indexing.access_epoch_deployment import (
    PROJECT_ROOT,
    DeploymentCommands,
    ObservedDeployment,
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
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import CONTEXT_ENDPOINT_DIGEST

if TYPE_CHECKING:
    from ai_workshop.infrastructure.local.control_process_windows import WindowsControlProcess


def _denied() -> ValueError:
    return ValueError("cutover_bootstrap_admin_denied")


def _pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values:
        if key in result:
            raise _denied()
        result[key] = value
    return result


def _same_public_object(actual: object, expected: dict[str, object]) -> bool:
    return type(actual) is dict and canonical_json(actual) == canonical_json(expected)


@dataclass(frozen=True, slots=True, eq=False)
class BootstrapAdministrator:
    epoch_id: UUID
    execution_id: UUID
    action_id: UUID
    container_id: str
    submission_id: UUID
    password: SecretStr = field(repr=False)
    audit_status: Literal["pending"] = field(default="pending", init=False)
    pending_audits: tuple[str, ...] = field(
        default=("administrator_authentication", "native_realm", "temporary_file_user_cleanup"),
        init=False,
    )


class RecordedBootstrapAdministrator:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        repository: ReservationReadPort,
        deployment: DeploymentCommands,
        bootstrap: ObservedDeployment,
        builder: BootstrapCommands,
        journal: ProtectedControlJournal,
        native: WindowsControlProcess,
        root: Path,
        binding_factory: BootstrapBindingFactory,
    ) -> None:
        self.epoch, self.repository, self.deployment, self.bootstrap = (
            epoch,
            repository,
            deployment,
            bootstrap,
        )
        self.builder, self.journal, self.native, self.root = builder, journal, native, root
        self.binding_factory = binding_factory
        self._tickets: dict[UUID, FreshSubmissionTicket] = {}
        self._command: BootstrapCommand | None = None
        self._credentials: set[BootstrapAdministrator] = set()
        try:
            self._owned()
        except Exception:
            raise _denied() from None

    def _owned(self) -> None:
        self.journal.lock.assert_owned(self.journal.owner)
        if (
            type(self.binding_factory) is not BootstrapBindingFactory
            or self.binding_factory.repository is not self.repository
            or self.binding_factory.journal is not self.journal
            or self.binding_factory.deployment is not self.deployment
        ):
            raise _denied()
        self.binding_factory.assert_issued(self.builder)
        self.deployment.assert_observed(self.bootstrap)
        if (
            self.root != PROJECT_ROOT
            or self.journal.root != PROJECT_ROOT
            or type(self.deployment) is not DeploymentCommands
            or type(self.builder) is not BootstrapCommands
            or self.deployment.epoch != self.epoch
            or self.bootstrap.kind != CutoverActionKind.START_BOOTSTRAP
            or self.bootstrap.execution_id != self.journal.owner.execution_id
            or str(self.bootstrap.execution_id) != self.epoch.binding.execution_id
            or self.builder.binding.container_id != self.bootstrap.container_id
            or self.builder.binding.execution_id != self.bootstrap.execution_id
            or str(self.builder.binding.epoch_id) != self.epoch.binding.access_epoch_id
            or self.builder.binding.original_security_absent is not True
            or hashlib.sha256(
                json.dumps([self.epoch.original.daemon_sha256, "ai-workshop"]).encode()
            ).hexdigest()
            != self.journal.lock.scope_sha256
        ):
            raise _denied()

    def _target(self) -> str:
        self._owned()
        return hashlib.sha256(
            canonical_json(
                {
                    "kind": CutoverActionKind.BOOTSTRAP_ADMIN.value,
                    "binary_sha256": original_process._binary_sha(),
                    "daemon_sha256": self.epoch.original.daemon_sha256,
                    "endpoint_sha256": CONTEXT_ENDPOINT_DIGEST,
                    "epoch_id": self.epoch.binding.access_epoch_id,
                    "execution_id": self.epoch.binding.execution_id,
                    "container_id": self.bootstrap.container_id,
                    "bootstrap_action_id": str(self.bootstrap.action_id),
                    "bootstrap_manifest_sha256": hashlib.sha256(
                        self.bootstrap.manifest_json.encode()
                    ).hexdigest(),
                    "operation": "automatic_elastic_reset",
                }
            ).encode()
        ).hexdigest()

    def _state(
        self,
        state: AccessEpochReadback,
        action: ReservedCutoverAction | None,
        *,
        recovery: bool = False,
    ) -> None:
        self._owned()
        if (
            state.prepared != self.epoch
            or state.executor_generation != self.journal.owner.executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or state.phase in {None, "verified", "receipted"}
        ):
            raise _denied()
        previous = state.actions if action is None else state.actions[:-1]
        if (
            tuple(x.action.kind for x in previous)
            != CUTOVER_ORDER[: CUTOVER_ORDER.index(CutoverActionKind.BOOTSTRAP_ADMIN)]
        ):
            raise _denied()
        sequence = 0
        for row in previous:
            if (
                row.outcome != "settled"
                or row.manifest_json is None
                or type(row.action.sequence) is not int
                or row.action.sequence != sequence + 1
                or type(row.event_sequence) is not int
                or row.event_sequence <= row.action.sequence
                or row.action.execution_id != self.journal.owner.execution_id
                or row.action.executor_generation != self.journal.owner.executor_generation
            ):
                raise _denied()
            sequence = row.event_sequence
        start = previous[-1]
        if (
            start.action.action_id != self.bootstrap.action_id
            or start.manifest_json != self.bootstrap.manifest_json
        ):
            raise _denied()
        if action is not None and (
            type(action) is not ReservedCutoverAction
            or type(action.kind) is not CutoverActionKind
            or action.kind != CutoverActionKind.BOOTSTRAP_ADMIN
            or action.execution_id != self.journal.owner.execution_id
            or action.executor_generation != self.journal.owner.executor_generation
            or type(action.sequence) is not int
            or action.sequence != sequence + 1
            or action.expected.preceding_sequence != sequence
            or not state.actions
            or state.actions[-1].action != action
            or state.actions[-1].outcome
            not in ({"pending", "unknown"} if recovery else {"pending"})
            or not recovery
            and (
                state.actions[-1].event_sequence != action.sequence
                or state.actions[-1].manifest_json is not None
            )
            or json.loads(action.expected.identity_json).get("target_sha256") != self._target()
        ):
            raise _denied()

    def _path(self, name: str) -> str:
        return str(
            self.root
            / ".local-data/access-epoch/private/control"
            / self.epoch.binding.execution_id
            / name
        )

    def _catalog_path(self) -> str:
        return self._path("administrator-catalog.dpapi")

    def _binding(self, action: ReservedCutoverAction) -> dict[str, object]:
        expected = json.loads(action.expected.identity_json)
        return {
            "schema_version": 1,
            "purpose": "bootstrap_administrator",
            "epoch_id": self.epoch.binding.access_epoch_id,
            "execution_id": str(action.execution_id),
            "executor_generation": action.executor_generation,
            "action_id": str(action.action_id),
            "sequence": action.sequence,
            "kind": action.kind.value,
            "submission_id": expected["submission_id"],
            "scope_sha256": self.journal.scope,
            "expected_sha256": hashlib.sha256(action.expected.identity_json.encode()).hexdigest(),
            "target_sha256": self._target(),
            "container_id": self.bootstrap.container_id,
            "bootstrap_action_id": str(self.bootstrap.action_id),
        }

    def _read(self, path: str) -> dict[str, Any] | None:
        self._owned()
        encrypted = self.journal.files.read(path)
        self._owned()
        if encrypted is None:
            return None
        if type(encrypted) is not bytes or not 0 < len(encrypted) <= 2_097_152:
            raise _denied()
        raw = self.journal.protection.unprotect(encrypted)
        self._owned()
        if type(raw) is not bytes or not 0 < len(raw) <= 1_048_576:
            raise _denied()
        result = json.loads(raw, object_pairs_hook=_pairs)
        if type(result) is not dict or canonical_json(result).encode() != raw:
            raise _denied()
        return result

    def _write_new(self, path: str, packet: dict[str, object]) -> None:
        self._owned()
        if self.journal.files.read(path) is not None:
            raise _denied()
        payload = canonical_json(packet).encode()
        self._owned()
        encrypted = self.journal.protection.protect(payload)
        self._owned()
        self.journal.files.write(path, encrypted)
        self._owned()
        observed = self._read(path)
        if observed is None or canonical_json(observed).encode() != payload:
            raise _denied()
        self._owned()

    async def prepare(self) -> FreshSubmissionTicket:
        try:
            self._owned()
            state = await self.repository.readback(self.epoch.binding.claim)
            self._state(state, None)
            if self._read(self._catalog_path()) is not None:
                raise _denied()
            ticket = self.journal.prepare_expected(
                CutoverActionKind.BOOTSTRAP_ADMIN, state.actions[-1].event_sequence, self._target()
            )
            self._tickets[ticket.submission_id] = ticket
            return ticket
        except Exception:
            raise _denied() from None

    @staticmethod
    def _child(record: ControlSubmissionRecord) -> dict[str, object]:
        if record.child is None:
            raise _denied()
        return {
            "pid": record.child.pid,
            "creation_time": record.child.creation_time,
            "job_id": str(record.child.job_id),
        }

    def _reset_command(self) -> BootstrapCommand:
        if self._command is None:
            self._command = self.builder.reset_password()
        self.builder.assert_reset_command(self._command)
        return self._command

    def _capture(
        self, record: ControlSubmissionRecord, stdout: bytes, stderr: bytes, exit_code: int
    ) -> None:
        if (
            type(stdout) is not bytes
            or type(stderr) is not bytes
            or len(stdout) > 262144
            or len(stderr) > 262144
        ):
            raise _denied()
        self._write_new(
            self._path(f"{record.action.action_id}.administrator-output.dpapi"),
            {
                "binding": self._binding(record.action),
                "child": self._child(record),
                "exit_code": exit_code,
                "stdout": base64.b64encode(stdout).decode("ascii"),
                "stderr": base64.b64encode(stderr).decode("ascii"),
            },
        )

    def _recover_private(self, action: ReservedCutoverAction) -> BootstrapAdministrator:
        self._owned()
        binding = self._binding(action)
        if not _same_public_object(self._read(self._catalog_path()), binding):
            raise _denied()
        record = self.journal.read(action)
        self._owned()
        if (
            record is None
            or record.state != "process_finished"
            or record.exit_code != 0
            or record.child is None
        ):
            raise _denied()
        output = self._read(self._path(f"{action.action_id}.administrator-output.dpapi"))
        if (
            output is None
            or set(output) != {"binding", "child", "exit_code", "stdout", "stderr"}
            or not _same_public_object(output["binding"], binding)
            or not _same_public_object(output["child"], self._child(record))
            or type(output["exit_code"]) is not int
            or output["exit_code"] != 0
            or type(output["stdout"]) is not str
            or type(output["stderr"]) is not str
        ):
            raise _denied()
        stdout = base64.b64decode(output["stdout"], validate=True)
        stderr = base64.b64decode(output["stderr"], validate=True)
        if len(stdout) > 130 or len(stderr) > 262144:
            raise _denied()
        path = self._path(f"{action.action_id}.administrator.dpapi")
        private = self._read(path)
        if private is None:
            # This may create a decode-only command on a fresh builder. No native
            # path is reachable here and the durable catalog forbids another run.
            password = self.builder.decode_reset(self._reset_command(), record.exit_code, stdout)
            self._write_new(
                path,
                {
                    "binding": binding,
                    "child": self._child(record),
                    "password": password.get_secret_value(),
                },
            )
        else:
            if (
                set(private) != {"binding", "child", "password"}
                or not _same_public_object(private["binding"], binding)
                or not _same_public_object(private["child"], self._child(record))
                or type(private["password"]) is not str
                or re.fullmatch(r"[!-~]{8,128}", private["password"]) is None
            ):
                raise _denied()
            password = SecretStr(private["password"])
        encoded = password.get_secret_value().encode("ascii")
        if stdout not in {encoded, encoded + b"\n", encoded + b"\r\n"}:
            raise _denied()
        self._owned()
        result = BootstrapAdministrator(
            UUID(self.epoch.binding.access_epoch_id),
            action.execution_id,
            action.action_id,
            self.bootstrap.container_id,
            record.submission_id,
            password,
        )
        self._credentials.add(result)
        return result

    def assert_credential(self, value: BootstrapAdministrator) -> None:
        try:
            self._owned()
            if type(value) is not BootstrapAdministrator or value not in self._credentials:
                raise _denied()
        except Exception:
            raise _denied() from None

    async def recover(self, action: ReservedCutoverAction) -> BootstrapAdministrator:
        try:
            self._owned()
            state = await self.repository.readback(self.epoch.binding.claim)
            self._state(state, action, recovery=True)
            result = self._recover_private(action)
            state = await self.repository.readback(self.epoch.binding.claim)
            self._state(state, action, recovery=True)
            return result
        except Exception:
            raise _denied() from None

    async def run(
        self, action: ReservedCutoverAction, ticket: FreshSubmissionTicket
    ) -> BootstrapAdministrator:
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
            state = await self.repository.readback(self.epoch.binding.claim)
            self._state(state, action)
            self._write_new(self._catalog_path(), self._binding(action))
            record = self.journal.begin(action, ticket)
            command = self._reset_command()
            env = {
                k: v
                for k, v in os.environ.items()
                if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT"}
            }
            self._owned()
            self.builder.assert_reset_command(command)
            token = self.native.create_suspended(
                command.argv, env, self.root, stdin=command.private_stdin or None
            )
            child = ControlProcessIdentity(
                token.child.pid, token.child.creation_time, token.child.job_id
            )
            record = self.journal.process_created(record, child)
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
            self._capture(record, result.stdout, result.stderr, result.exit_code)
            record = self.journal.process_finished(record, child, result.exit_code)
            closing, token = token, None
            self.native.close(closing)
            self._owned()
            state = await self.repository.readback(self.epoch.binding.claim)
            self._state(state, action, recovery=True)
            credential = self._recover_private(action)
            state = await self.repository.readback(self.epoch.binding.claim)
            self._state(state, action, recovery=True)
            return credential
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
