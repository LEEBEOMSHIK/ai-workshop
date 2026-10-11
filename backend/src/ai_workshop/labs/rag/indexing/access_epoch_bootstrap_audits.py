"""Recorded bootstrap security reads; reset success alone never passes an audit."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from ai_workshop.labs.rag.indexing import access_epoch_process as original_process
from ai_workshop.labs.rag.indexing.access_epoch_admin_process import (
    BootstrapAdministrator,
    RecordedBootstrapAdministrator,
)
from ai_workshop.labs.rag.indexing.access_epoch_bootstrap_binding import BootstrapBindingFactory
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_process import ReservationReadPort
from ai_workshop.labs.rag.indexing.access_epoch_submission import (
    ControlProcessIdentity,
    ControlSubmissionRecord,
    ProtectedControlJournal,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    ReservedCutoverAction,
    canonical_json,
)

if TYPE_CHECKING:
    from ai_workshop.infrastructure.local.control_process_windows import WindowsControlProcess

_PURPOSES = ("authenticate", "users", "api_keys", "file_users", "file_roles")


def _denied() -> ValueError:
    return ValueError("bootstrap_security_audit_unverified")


@dataclass(frozen=True, slots=True, eq=False)
class ObservedBootstrapSecurity:
    manifest_json: str


class RecordedBootstrapAudits:
    def __init__(
        self,
        administrator: RecordedBootstrapAdministrator,
        factory: BootstrapBindingFactory,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        native: WindowsControlProcess,
    ) -> None:
        self.administrator, self.factory = administrator, factory
        self.repository, self.journal, self.native = repository, journal, native
        self._issued: dict[ObservedBootstrapSecurity, str] = {}
        self._active_credential: BootstrapAdministrator | None = None

    def _guard(self) -> None:
        if self._active_credential is None:
            raise _denied()
        self._owned(self._active_credential)

    def _owned(self, credential: BootstrapAdministrator) -> None:
        self.journal.lock.assert_owned(self.journal.owner)
        self.administrator.assert_credential(credential)
        self.factory.assert_issued(self.administrator.builder)
        if (
            self.administrator.binding_factory is not self.factory
            or self.factory.repository is not self.repository
            or self.factory.journal is not self.journal
        ):
            raise _denied()

    async def _state(
        self, action: ReservedCutoverAction, credential: BootstrapAdministrator
    ) -> None:
        self._owned(credential)
        epoch = self.administrator.epoch
        state = await self.repository.readback(epoch.binding.claim)
        self._owned(credential)
        if (
            type(action) is not ReservedCutoverAction
            or action.kind
            not in {CutoverActionKind.BOOTSTRAP_ADMIN, CutoverActionKind.REVOKE_HISTORICAL}
            or state.prepared != epoch
            or state.executor_generation != self.journal.owner.executor_generation
            or action.execution_id != self.journal.owner.execution_id
            or action.executor_generation != self.journal.owner.executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or not state.actions
            or state.actions[-1].action != action
            or state.actions[-1].outcome not in {"pending", "unknown"}
            or tuple(x.action.kind for x in state.actions[:-1])
            != CUTOVER_ORDER[: CUTOVER_ORDER.index(action.kind)]
            or any(x.outcome != "settled" for x in state.actions[:-1])
            or action.kind == CutoverActionKind.BOOTSTRAP_ADMIN
            and credential.action_id != action.action_id
            or credential.container_id != self.administrator.bootstrap.container_id
        ):
            raise _denied()

    def _binding(self, action: ReservedCutoverAction) -> dict[str, object]:
        return {
            "schema_version": 1,
            "parent_action_id": str(action.action_id),
            "execution_id": str(action.execution_id),
            "executor_generation": action.executor_generation,
            "kind": action.kind.value,
            "bootstrap_container_id": self.administrator.bootstrap.container_id,
            "bootstrap_action_id": str(self.administrator.bootstrap.action_id),
            "binary_sha256": original_process._binary_sha(),
        }

    def _path(self, action: ReservedCutoverAction, suffix: str) -> str:
        return str(
            self.journal.root
            / ".local-data/access-epoch/private/control"
            / str(action.execution_id)
            / suffix
        )

    def _read(self, path: str) -> dict[str, Any] | None:
        self._guard()
        encrypted = self.journal.files.read(path)
        self._guard()
        if encrypted is None:
            return None
        if type(encrypted) is not bytes or not 0 < len(encrypted) <= 2097152:
            raise _denied()
        raw = self.journal.protection.unprotect(encrypted)
        self._guard()
        if type(raw) is not bytes or not 0 < len(raw) <= 1048576:
            raise _denied()
        value = json.loads(raw)
        if type(value) is not dict or canonical_json(value).encode() != raw:
            raise _denied()
        return value

    def _write(self, path: str, packet: dict[str, Any]) -> None:
        self._guard()
        payload = canonical_json(packet).encode()
        encrypted = self.journal.protection.protect(payload)
        self._guard()
        self.journal.files.write(path, encrypted)
        self._guard()
        observed = self._read(path)
        if observed is None or canonical_json(observed).encode() != payload:
            raise _denied()
        self._guard()

    def _capture_binding(
        self, action: ReservedCutoverAction, purpose: str, record: ControlSubmissionRecord
    ) -> dict[str, object]:
        if record.child is None:
            raise _denied()
        return {
            **self._binding(action),
            "purpose": purpose,
            "helper_action_id": str(record.action.action_id),
            "helper_expected": record.action.expected.identity_json,
            "child": {
                "pid": record.child.pid,
                "creation_time": record.child.creation_time,
                "job_id": str(record.child.job_id),
            },
        }

    def _decode(self, purpose: str, exit_code: int, stdout: bytes) -> None:
        builder = self.administrator.builder
        if purpose == "authenticate":
            builder.decode_authenticated(exit_code, stdout)
        elif purpose == "users":
            builder.decode_users(exit_code, stdout)
        elif purpose == "api_keys":
            builder.decode_api_keys(exit_code, stdout)
        else:
            builder.decode_file_realm_empty(exit_code, stdout)

    async def run(
        self, action: ReservedCutoverAction, credential: BootstrapAdministrator
    ) -> ObservedBootstrapSecurity:
        record, token, helper_journal = None, None, None
        if self._active_credential is not None:
            raise _denied()
        self._active_credential = credential
        try:
            await self._state(action, credential)
            path = self._path(action, f"{action.action_id}.security-audits.dpapi")
            binding = self._binding(action)
            packet = self._read(path)
            if packet is None:
                packet = {"binding": binding, "steps": []}
                self._write(path, packet)
                self._owned(credential)
            if set(packet) != {"binding", "steps"} or canonical_json(
                packet["binding"]
            ) != canonical_json(binding):
                raise _denied()
            steps = packet["steps"]
            if type(steps) is not list or len(steps) > len(_PURPOSES):
                raise _denied()
            for i, step in enumerate(steps):
                if type(step) is not dict or set(step) != {
                    "purpose",
                    "action_id",
                    "expected",
                    "complete",
                }:
                    raise _denied()
                if step["purpose"] != _PURPOSES[i] or step["complete"] is not True:
                    raise _denied()
                helper = ReservedCutoverAction(
                    UUID(step["action_id"]),
                    action.execution_id,
                    action.sequence,
                    action.kind,
                    ControlExpectedIdentity(step["expected"], action.sequence - 1),
                    action.executor_generation,
                )
                expected_target = hashlib.sha256(
                    canonical_json({**binding, "purpose": step["purpose"]}).encode()
                ).hexdigest()
                if (
                    json.loads(helper.expected.identity_json).get("target_sha256")
                    != expected_target
                ):
                    raise _denied()
                previous = self.journal.read(helper)
                if (
                    previous is None
                    or previous.state != "process_finished"
                    or previous.exit_code != 0
                ):
                    raise _denied()
                self._guard()
                capture = self._read(
                    self._path(action, f"{helper.action_id}.security-output.dpapi")
                )
                if (
                    capture is None
                    or set(capture) != {"binding", "exit_code", "stdout", "stderr"}
                    or canonical_json(capture["binding"])
                    != canonical_json(self._capture_binding(action, step["purpose"], previous))
                    or type(capture["exit_code"]) is not int
                    or capture["exit_code"] != 0
                    or type(capture["stdout"]) is not str
                    or type(capture["stderr"]) is not str
                ):
                    raise _denied()
                restored = base64.b64decode(capture["stdout"], validate=True)
                errors = base64.b64decode(capture["stderr"], validate=True)
                if len(restored) + len(errors) > 524288:
                    raise _denied()
                self._decode(step["purpose"], capture["exit_code"], restored)
            for purpose in _PURPOSES[len(steps) :]:
                await self._state(action, credential)
                command = self.administrator.builder.audit_command(credential.password, purpose)
                target = hashlib.sha256(
                    canonical_json({**binding, "purpose": purpose}).encode()
                ).hexdigest()
                helper_journal = ProtectedControlJournal(
                    self.journal.root,
                    self.journal.protection,
                    self.journal.files,
                    self.journal.lock,
                    self.journal.owner,
                    self.journal.scope,
                )
                ticket = helper_journal.prepare_expected(action.kind, action.sequence - 1, target)
                helper = ReservedCutoverAction(
                    uuid4(),
                    action.execution_id,
                    action.sequence,
                    action.kind,
                    ticket.expected,
                    action.executor_generation,
                )
                steps.append(
                    {
                        "purpose": purpose,
                        "action_id": str(helper.action_id),
                        "expected": helper.expected.identity_json,
                        "complete": False,
                    }
                )
                self._write(path, packet)
                self._owned(credential)
                record = helper_journal.begin(helper, ticket)
                self.administrator.builder.assert_audit_command(command, purpose)
                env = {
                    k: v
                    for k, v in os.environ.items()
                    if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT"}
                }
                self._owned(credential)
                token = self.native.create_suspended(
                    command.argv, env, self.journal.root, stdin=command.private_stdin or None
                )
                child = ControlProcessIdentity(
                    token.child.pid, token.child.creation_time, token.child.job_id
                )
                record = helper_journal.process_created(record, child)
                self._owned(credential)
                self.native.resume(token)
                self._owned(credential)
                result = self.native.wait(token, 45000)
                self._owned(credential)
                if (
                    ControlProcessIdentity(
                        result.child.pid, result.child.creation_time, result.child.job_id
                    )
                    != child
                ):
                    raise _denied()
                output_path = self._path(action, f"{helper.action_id}.security-output.dpapi")
                if self.journal.files.read(output_path) is not None:
                    raise _denied()
                if (
                    type(result.stdout) is not bytes
                    or type(result.stderr) is not bytes
                    or len(result.stdout) + len(result.stderr) > 524288
                ):
                    raise _denied()
                self._write(
                    output_path,
                    {
                        "binding": self._capture_binding(action, purpose, record),
                        "exit_code": result.exit_code,
                        "stdout": base64.b64encode(result.stdout).decode(),
                        "stderr": base64.b64encode(result.stderr).decode(),
                    },
                )
                self._owned(credential)
                record = helper_journal.process_finished(record, child, result.exit_code)
                closing, token = token, None
                self.native.close(closing)
                self._owned(credential)
                self._decode(purpose, result.exit_code, result.stdout)
                await self._state(action, credential)
                steps[-1]["complete"] = True
                self._write(path, packet)
                self._owned(credential)
                record = None
            await self._state(action, credential)
            value = ObservedBootstrapSecurity(
                canonical_json(
                    {
                        **binding,
                        "administrator_authentication": "reserved_elastic",
                        "users": "reserved_builtins_only",
                        "historical_api_keys": "empty",
                        "file_realm": "empty",
                        "recorded_read_helpers": len(_PURPOSES),
                    }
                )
            )
            self._issued[value] = value.manifest_json
            return value
        except BaseException as exc:
            if (
                helper_journal is not None
                and record is not None
                and record.state in {"intent", "process_created"}
            ):
                with suppress(BaseException):
                    helper_journal.unknown(record)
            if isinstance(exc, Exception):
                raise _denied() from None
            raise
        finally:
            if token is not None:
                with suppress(BaseException):
                    self.native.close(token)
            self._active_credential = None

    def assert_issued(self, value: ObservedBootstrapSecurity) -> None:
        self.journal.lock.assert_owned(self.journal.owner)
        self.factory.assert_issued(self.administrator.builder)
        if (
            type(value) is not ObservedBootstrapSecurity
            or self._issued.get(value) != value.manifest_json
        ):
            raise _denied()
