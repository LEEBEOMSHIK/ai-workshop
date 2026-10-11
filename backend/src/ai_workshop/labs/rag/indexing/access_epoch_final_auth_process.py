"""Six owned, recorded final-role reads; no caller response can settle this runner."""

import base64
import hashlib
import json
import os
from contextlib import suppress
from dataclasses import dataclass
from typing import Any
from uuid import UUID, uuid4

from ai_workshop.infrastructure.local.control_process_windows import (
    ChildToken,
    WindowsControlProcess,
)
from ai_workshop.infrastructure.search.access_credentials import ServiceRole
from ai_workshop.labs.rag.indexing import access_epoch_process as original_process
from ai_workshop.labs.rag.indexing.access_epoch_deployment import (
    PROJECT_ROOT,
    DeploymentCommands,
    ObservedDeployment,
)
from ai_workshop.labs.rag.indexing.access_epoch_final_auth import (
    AuthenticatedFinalKey,
    FinalAuthBinding,
    FinalAuthCommand,
    FinalAuthCommands,
    FinalAuthObservation,
    FinalAuthResponse,
    FinalRoleCheck,
)
from ai_workshop.labs.rag.indexing.access_epoch_final_auth_binding import FinalAuthBindingFactory
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_process import ReservationReadPort
from ai_workshop.labs.rag.indexing.access_epoch_submission import (
    ControlProcessIdentity,
    ControlSubmissionRecord,
    FreshSubmissionTicket,
    ProtectedControlJournal,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlExpectedIdentity,
    CutoverActionKind,
    ReservedCutoverAction,
    canonical_json,
)

_ROLES: tuple[ServiceRole, ...] = ("reader", "writer", "collector")
_STEPS = tuple((role, purpose) for role in _ROLES for purpose in ("authenticate", "privileges"))


def _denied() -> ValueError:
    return ValueError("final_auth_process_denied")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in items:
        if key in value:
            raise _denied()
        value[key] = item
    return value


def _same(value: object, expected: dict[str, Any]) -> bool:
    return type(value) is dict and canonical_json(value) == canonical_json(expected)


@dataclass(frozen=True, slots=True, eq=False)
class FreshFinalAuthTicket:
    nonce: UUID
    execution_id: UUID
    executor_generation: str
    sequence: int
    kind: CutoverActionKind
    expected: ControlExpectedIdentity


class RecordedFinalAuthentication:
    def __init__(
        self,
        factory: FinalAuthBindingFactory,
        binding: FinalAuthBinding,
        deployment: DeploymentCommands,
        final: ObservedDeployment,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        native: WindowsControlProcess,
    ) -> None:
        self.factory, self.binding, self.deployment, self.final = (
            factory,
            binding,
            deployment,
            final,
        )
        self.repository, self.journal, self.native = repository, journal, native
        self._tickets: dict[UUID, FreshFinalAuthTicket] = {}
        self._prepared = False
        self._running = False
        self._issued: dict[FinalAuthObservation, str] = {}
        try:
            self._owned()
        except Exception:
            raise _denied() from None

    def _owned(self) -> None:
        if (
            type(self.factory) is not FinalAuthBindingFactory
            or type(self.deployment) is not DeploymentCommands
            or type(self.native) is not WindowsControlProcess
            or self.factory.repository is not self.repository
            or self.factory.journal is not self.journal
            or self.factory.deployment is not self.deployment
        ):
            raise _denied()
        self.journal._owned()
        self.factory.assert_issued(self.binding)
        self.deployment.assert_observed(self.final)
        epoch = self.deployment.epoch
        if (
            self.journal.root != PROJECT_ROOT
            or self.binding.epoch_id != UUID(epoch.binding.access_epoch_id)
            or self.binding.execution_id != self.journal.owner.execution_id
            or epoch.binding.execution_id != str(self.journal.owner.execution_id)
            or self.final.kind != CutoverActionKind.START_SECURED
            or self.final.execution_id != self.binding.execution_id
            or self.final.container_id != self.binding.container_id
        ):
            raise _denied()
        self.journal._owned()

    def _base(self) -> dict[str, object]:
        epoch = self.deployment.epoch
        claim = epoch.binding.claim
        return {
            "schema_version": 1,
            "kind": "final_auth_six_reads",
            "binding_nonce": str(self.binding.nonce),
            "epoch_id": str(self.binding.epoch_id),
            "execution_id": str(self.binding.execution_id),
            "executor_generation": self.journal.owner.executor_generation,
            "final_container_id": self.final.container_id,
            "final_action_id": str(self.final.action_id),
            "final_manifest_sha256": hashlib.sha256(self.final.manifest_json.encode()).hexdigest(),
            "binary_sha256": original_process._binary_sha(),
            "scope_sha256": self.journal.scope,
            "request_id": str(claim.request_id),
            "actor_id": str(claim.actor_id),
            "snapshot_sha256": claim.snapshot.sha256,
            "gate_revision": claim.revision,
            "keys": {
                key.role: {"id": key.key_id, "issuance": str(key.issuance_id)}
                for key in self.binding.keys
            },
            "descriptors": {role: self.binding.permissions.descriptor(role) for role in _ROLES},
        }

    def _expected(self, nonce: UUID, preceding: int) -> ControlExpectedIdentity:
        return ControlExpectedIdentity(
            canonical_json(
                {**self._base(), "intent_nonce": str(nonce), "preceding_sequence": preceding}
            ),
            preceding,
        )

    async def _state(
        self, action: ReservedCutoverAction | None = None, *, fresh: bool = False
    ) -> int:
        self._owned()
        epoch = self.deployment.epoch
        state = await self.repository.readback(epoch.binding.claim)
        self._owned()
        kinds = CUTOVER_ORDER[:-1] if action is None else CUTOVER_ORDER
        if (
            state.prepared != epoch
            or state.executor_generation != self.journal.owner.executor_generation
            or state.phase != "secured_started"
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or tuple(x.action.kind for x in state.actions) != kinds
            or CUTOVER_ORDER[-1] != CutoverActionKind.VERIFY_ACCESS
        ):
            raise _denied()
        sequence = 0
        preceding = 0
        for i, row in enumerate(state.actions):
            item = row.action
            parent = action is not None and i == len(CUTOVER_ORDER) - 1
            if (
                type(item) is not ReservedCutoverAction
                or type(item.action_id) is not UUID
                or type(item.sequence) is not int
                or item.sequence != sequence + 1
                or type(item.kind) is not CutoverActionKind
                or type(item.expected) is not ControlExpectedIdentity
                or type(item.expected.preceding_sequence) is not int
                or item.expected.preceding_sequence != sequence
                or item.execution_id != self.journal.owner.execution_id
                or item.executor_generation != self.journal.owner.executor_generation
                or type(row.event_sequence) is not int
                or (
                    not parent
                    and (
                        row.outcome != "settled"
                        or row.manifest_json is None
                        or row.event_sequence <= item.sequence
                    )
                )
                or (
                    parent
                    and (
                        item != action
                        or row.outcome not in ({"pending"} if fresh else {"pending", "unknown"})
                    )
                )
                or (
                    parent
                    and row.outcome == "pending"
                    and (row.manifest_json is not None or row.event_sequence != item.sequence)
                )
                or (parent and row.outcome == "unknown" and row.event_sequence <= item.sequence)
            ):
                raise _denied()
            if parent:
                preceding = sequence
            sequence = row.event_sequence
        started = state.actions[CUTOVER_ORDER.index(CutoverActionKind.START_SECURED)]
        tls = state.actions[CUTOVER_ORDER.index(CutoverActionKind.PREPARE_TLS)]
        key_parent = state.actions[CUTOVER_ORDER.index(CutoverActionKind.ISSUE_ROLE_KEY)]
        key_group = {
            "schema_version": 1,
            "execution_id": str(self.binding.execution_id),
            "parent_action_id": str(key_parent.action.action_id),
            "keys": {key.role: key.key_id for key in self.binding.keys},
            "issuances": {key.role: str(key.issuance_id) for key in self.binding.keys},
            "permissions": {
                role: hashlib.sha256(
                    canonical_json(dict(self.binding.permissions.descriptor(role))).encode()
                ).hexdigest()
                for role in _ROLES
            },
        }
        if (
            started.action.action_id != self.final.action_id
            or started.manifest_json != self.final.manifest_json
            or tls.manifest_json != self.deployment.tls.manifest_json
            or key_parent.manifest_json != canonical_json(key_group)
        ):
            raise _denied()
        if action is not None:
            if (
                type(action) is not ReservedCutoverAction
                or type(action.expected) is not ControlExpectedIdentity
                or type(action.expected.preceding_sequence) is not int
            ):
                raise _denied()
            value = json.loads(action.expected.identity_json, object_pairs_hook=_pairs)
            nonce = UUID(value["intent_nonce"])
            if (
                str(nonce) != value["intent_nonce"]
                or nonce.int == 0
                or action.expected != self._expected(nonce, preceding)
            ):
                raise _denied()
        return sequence

    def _catalog_path(self, action: ReservedCutoverAction) -> str:
        return str(
            self.journal.root
            / ".local-data/access-epoch/private/control"
            / str(action.execution_id)
            / f"{action.action_id}.final-auth-catalog.dpapi"
        )

    def _output_path(self, action: ReservedCutoverAction, helper_id: str) -> str:
        parsed = UUID(helper_id)
        if str(parsed) != helper_id:
            raise _denied()
        return str(
            self.journal.root
            / ".local-data/access-epoch/private/control"
            / str(action.execution_id)
            / f"{helper_id}.final-auth-output.dpapi"
        )

    def _read(self, path: str) -> dict[str, Any] | None:
        self._owned()
        encrypted = self.journal.files.read(path)
        self._owned()
        if encrypted is None:
            return None
        if type(encrypted) is not bytes or not 0 < len(encrypted) <= 2097152:
            raise _denied()
        raw = self.journal.protection.unprotect(encrypted)
        self._owned()
        if type(raw) is not bytes or not 0 < len(raw) <= 1048576:
            raise _denied()
        value = json.loads(raw, object_pairs_hook=_pairs)
        if type(value) is not dict or canonical_json(value).encode() != raw:
            raise _denied()
        return value

    def _write(
        self, path: str, packet: dict[str, Any], previous: dict[str, Any] | None = None
    ) -> None:
        current = self._read(path)
        if (previous is None and current is not None) or (
            previous is not None and not _same(current, previous)
        ):
            raise _denied()
        payload = canonical_json(packet).encode()
        encrypted = self.journal.protection.protect(payload)
        self._owned()
        self.journal.files.write(path, encrypted)
        self._owned()
        if not _same(self._read(path), packet):
            raise _denied()

    def _parent_binding(self, action: ReservedCutoverAction) -> dict[str, object]:
        return {
            **self._base(),
            "parent_action_id": str(action.action_id),
            "parent_expected": action.expected.identity_json,
            "sequence": action.sequence,
        }

    def _target(self, action: ReservedCutoverAction, role: ServiceRole, purpose: str) -> str:
        return hashlib.sha256(
            canonical_json(
                {**self._parent_binding(action), "role": role, "purpose": purpose}
            ).encode()
        ).hexdigest()

    def _capture_binding(
        self,
        action: ReservedCutoverAction,
        role: ServiceRole,
        purpose: str,
        record: ControlSubmissionRecord,
    ) -> dict[str, object]:
        if record.child is None:
            raise _denied()
        return {
            **self._parent_binding(action),
            "role": role,
            "purpose": purpose,
            "helper_action_id": str(record.action.action_id),
            "helper_expected": record.action.expected.identity_json,
            "child": {
                "pid": record.child.pid,
                "creation_time": record.child.creation_time,
                "job_id": str(record.child.job_id),
            },
        }

    async def prepare(self) -> FreshFinalAuthTicket:
        try:
            self._owned()
            if self._prepared:
                raise _denied()
            self._prepared = True
            preceding = await self._state()
            nonce = uuid4()
            ticket = FreshFinalAuthTicket(
                nonce,
                self.binding.execution_id,
                self.journal.owner.executor_generation,
                preceding + 1,
                CutoverActionKind.VERIFY_ACCESS,
                self._expected(nonce, preceding),
            )
            self._tickets[nonce] = ticket
            return ticket
        except Exception:
            raise _denied() from None

    def _plans(
        self, action: ReservedCutoverAction
    ) -> tuple[
        dict[str, Any],
        list[tuple[ProtectedControlJournal, ReservedCutoverAction, FreshSubmissionTicket]],
    ]:
        plans = []
        steps = []
        for role, purpose in _STEPS:
            journal = ProtectedControlJournal(
                self.journal.root,
                self.journal.protection,
                self.journal.files,
                self.journal.lock,
                self.journal.owner,
                self.journal.scope,
            )
            ticket = journal.prepare_expected(
                action.kind, action.sequence - 1, self._target(action, role, purpose)
            )
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
                    "role": role,
                    "purpose": purpose,
                    "action_id": str(helper.action_id),
                    "expected": helper.expected.identity_json,
                    "complete": False,
                }
            )
            plans.append((journal, helper, ticket))
        return {"binding": self._parent_binding(action), "steps": steps}, plans

    @staticmethod
    def _command(
        builder: FinalAuthCommands,
        role: ServiceRole,
        purpose: str,
        authenticated: dict[ServiceRole, AuthenticatedFinalKey],
    ) -> FinalAuthCommand:
        return (
            builder.authenticate(role)
            if purpose == "authenticate"
            else builder.privileges(authenticated[role])
        )

    @staticmethod
    def _decode(
        builder: FinalAuthCommands,
        command: FinalAuthCommand,
        response: FinalAuthResponse,
        authenticated: dict[ServiceRole, AuthenticatedFinalKey],
        checks: list[FinalRoleCheck],
    ) -> None:
        if command.purpose == "authenticate":
            authenticated[command.role] = builder.decode_authenticated(command, response)
        else:
            checks.append(builder.decode_privileges(command, response))

    async def _recover(self, action: ReservedCutoverAction) -> FinalAuthObservation:
        await self._state(action)
        packet = self._read(self._catalog_path(action))
        if (
            packet is None
            or set(packet) != {"binding", "steps"}
            or not _same(packet["binding"], self._parent_binding(action))
        ):
            raise _denied()
        steps = packet["steps"]
        if type(steps) is not list or len(steps) != len(_STEPS):
            raise _denied()
        builder = FinalAuthCommands(self.binding, self.factory)
        authenticated: dict[ServiceRole, AuthenticatedFinalKey] = {}
        checks: list[FinalRoleCheck] = []
        helper_ids: set[UUID] = set()
        for (role, purpose), step in zip(_STEPS, steps, strict=True):
            await self._state(action)
            if (
                type(step) is not dict
                or set(step) != {"role", "purpose", "action_id", "expected", "complete"}
                or step["role"] != role
                or step["purpose"] != purpose
                or step["complete"] is not True
                or type(step["action_id"]) is not str
                or type(step["expected"]) is not str
            ):
                raise _denied()
            helper_id = UUID(step["action_id"])
            if (
                str(helper_id) != step["action_id"]
                or helper_id in helper_ids
                or helper_id == action.action_id
            ):
                raise _denied()
            helper_ids.add(helper_id)
            helper = ReservedCutoverAction(
                helper_id,
                action.execution_id,
                action.sequence,
                action.kind,
                ControlExpectedIdentity(step["expected"], action.sequence - 1),
                action.executor_generation,
            )
            if json.loads(step["expected"], object_pairs_hook=_pairs).get(
                "target_sha256"
            ) != self._target(action, role, purpose):
                raise _denied()
            record = self.journal.read(helper)
            if (
                record is None
                or record.state != "process_finished"
                or type(record.exit_code) is not int
                or record.exit_code != 0
            ):
                raise _denied()
            capture = self._read(self._output_path(action, step["action_id"]))
            if (
                capture is None
                or set(capture) != {"binding", "exit_code", "stdout", "stderr"}
                or not _same(
                    capture["binding"], self._capture_binding(action, role, purpose, record)
                )
                or type(capture["exit_code"]) is not int
                or capture["exit_code"] != 0
                or type(capture["stdout"]) is not str
                or type(capture["stderr"]) is not str
            ):
                raise _denied()
            stdout, stderr = (
                base64.b64decode(capture["stdout"], validate=True),
                base64.b64decode(capture["stderr"], validate=True),
            )
            if (
                len(stdout) > 262144
                or len(stdout) + len(stderr) > 524288
                or base64.b64encode(stdout).decode() != capture["stdout"]
                or base64.b64encode(stderr).decode() != capture["stderr"]
            ):
                raise _denied()
            command = self._command(builder, role, purpose, authenticated)
            self._decode(
                builder, command, FinalAuthResponse(record.exit_code, stdout), authenticated, checks
            )
        await self._state(action)
        result = builder.complete(tuple(checks))
        manifest = canonical_json(
            {
                **json.loads(result.manifest_json),
                "parent_action_id": str(action.action_id),
                "recorded_read_helpers": 6,
            }
        )
        observed = FinalAuthObservation(
            result.epoch_id, result.execution_id, result.container_id, manifest
        )
        self._issued[observed] = manifest
        return observed

    async def run(
        self, action: ReservedCutoverAction, ticket: FreshFinalAuthTicket | None = None
    ) -> FinalAuthObservation:
        record: ControlSubmissionRecord | None = None
        helper_journal: ProtectedControlJournal | None = None
        token: ChildToken | None = None
        if self._running:
            raise _denied()
        self._running = True
        try:
            self._owned()
            if ticket is None:
                return await self._recover(action)
            if (
                type(ticket) is not FreshFinalAuthTicket
                or self._tickets.pop(ticket.nonce, None) is not ticket
                or type(action) is not ReservedCutoverAction
                or action.expected != ticket.expected
                or action.sequence != ticket.sequence
                or action.kind != ticket.kind
            ):
                raise _denied()
            await self._state(action, fresh=True)
            packet, plans = self._plans(action)
            self._write(self._catalog_path(action), packet)
            builder = FinalAuthCommands(self.binding, self.factory)
            authenticated: dict[ServiceRole, AuthenticatedFinalKey] = {}
            checks: list[FinalRoleCheck] = []
            for i, ((role, purpose), (helper_journal, helper, submission)) in enumerate(
                zip(_STEPS, plans, strict=True)
            ):
                await self._state(action, fresh=True)
                command = self._command(builder, role, purpose, authenticated)
                builder.assert_command(command)
                record = helper_journal.begin(helper, submission)
                await self._state(action, fresh=True)
                builder.assert_command(command)
                env = {
                    key: value
                    for key, value in os.environ.items()
                    if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT"}
                }
                self._owned()
                token = self.native.create_suspended(
                    command.argv, env, self.journal.root, stdin=command.private_stdin
                )
                child = ControlProcessIdentity(
                    token.child.pid, token.child.creation_time, token.child.job_id
                )
                record = helper_journal.process_created(record, child)
                await self._state(action, fresh=True)
                builder.assert_command(command)
                self.native.resume(token)
                # Native wait sends private stdin. Never enter it after ownership/DB loss.
                await self._state(action, fresh=True)
                builder.assert_command(command)
                result = self.native.wait(token, 45000)
                self._owned()
                if (
                    result.child is not token.child
                    or type(result.exit_code) is not int
                    or type(result.stdout) is not bytes
                    or type(result.stderr) is not bytes
                    or len(result.stdout) > 262144
                    or len(result.stdout) + len(result.stderr) > 524288
                ):
                    raise _denied()
                await self._state(action, fresh=True)
                self._write(
                    self._output_path(action, str(helper.action_id)),
                    {
                        "binding": self._capture_binding(action, role, purpose, record),
                        "exit_code": result.exit_code,
                        "stdout": base64.b64encode(result.stdout).decode(),
                        "stderr": base64.b64encode(result.stderr).decode(),
                    },
                )
                record = helper_journal.process_finished(record, child, result.exit_code)
                closing, token = token, None
                self.native.close(closing)
                self._owned()
                self._decode(
                    builder,
                    command,
                    FinalAuthResponse(result.exit_code, result.stdout),
                    authenticated,
                    checks,
                )
                await self._state(action, fresh=True)
                previous = json.loads(canonical_json(packet))
                packet["steps"][i]["complete"] = True
                self._write(self._catalog_path(action), packet, previous)
                record = None
            # Return only revalidated protected native captures, not live caller DTOs.
            return await self._recover(action)
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
            self._running = False

    def assert_issued(self, observation: FinalAuthObservation) -> None:
        try:
            self._owned()
            if (
                type(observation) is not FinalAuthObservation
                or self._issued.get(observation) != observation.manifest_json
            ):
                raise _denied()
        except Exception:
            raise _denied() from None
