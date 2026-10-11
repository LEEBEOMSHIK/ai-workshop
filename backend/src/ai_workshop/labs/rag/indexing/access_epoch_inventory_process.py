"""Finite recorded inventory helpers; no parent settlement or completeness proof.

Recovery requires the same retained live issuer, binding and native instance.
Private captures cannot be hydrated into authority after a controller restart.
"""

import base64
import hashlib
import json
import os
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

from ai_workshop.infrastructure.local.control_process_windows import (
    ChildToken,
    WindowsControlProcess,
)
from ai_workshop.labs.rag.indexing import access_epoch_process as original_process
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from ai_workshop.labs.rag.indexing.access_epoch_inventory_binding import (
    InventoryReadBinding,
    InventoryReadBindingFactory,
)
from ai_workshop.labs.rag.indexing.access_epoch_inventory_commands import (
    InventoryCommand,
    InventoryCommands,
    InventoryResponse,
)
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

_MAX_SLOTS = 512
_MAX_BODY = 262144
_MAX_TOTAL_BODY = 16 * 1024 * 1024
_MAX_CAPTURE_MEMORY = 16 * 1024 * 1024
_KINDS = {
    "original": CutoverActionKind.STOP_OLD,
    "bootstrap": CutoverActionKind.STOP_BOOTSTRAP,
    "final": CutoverActionKind.VERIFY_ACCESS,
}
_PURPOSES = {
    "listing",
    "cluster_info",
    "cluster_state",
    "nodes_info",
    "nodes_docs",
    "identity_state",
    "metadata",
    "count",
    "provenance_count",
}


def _denied() -> ValueError:
    return ValueError("inventory_process_denied")


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise _denied()
        result[key] = value
    return result


def _same(value: object, expected: object) -> bool:
    if value is None or expected is None:
        return value is expected
    return (
        type(value) is dict
        and type(expected) is dict
        and canonical_json(value) == canonical_json(expected)
    )


@dataclass(frozen=True, slots=True, eq=False)
class CapturedInventoryRead:
    parent: ReservedCutoverAction = field(repr=False)
    phase: str
    round: int
    purpose: str
    index_name: str | None = field(repr=False)
    private_body: bytes = field(repr=False)


@dataclass(slots=True)
class _LiveContext:
    factory: InventoryReadBindingFactory = field(repr=False)
    binding: InventoryReadBinding = field(repr=False)
    repository: ReservationReadPort = field(repr=False)
    journal: ProtectedControlJournal = field(repr=False)
    native: WindowsControlProcess = field(repr=False)
    binary_sha: str
    running: bool = False
    poisoned: bool = False
    initialized: bool = False
    catalog: bytes | None = field(default=None, repr=False)
    prefix: tuple[object, ...] | None = field(default=None, repr=False)
    commands: dict[str, tuple[tuple[str, ...], bytes]] = field(default_factory=dict, repr=False)
    captures: dict[str, tuple[ControlProcessIdentity, int, bytes, bytes]] = field(
        default_factory=dict, repr=False
    )


# Parent-scoped, process-lifetime refusal memory also covers missing first-write
# ACK/file. A new factory/nonce cannot silently reopen that same reserved parent.
_LIVE: dict[tuple[UUID, str, UUID], _LiveContext] = {}


class RecordedInventoryReads:
    def __init__(
        self,
        factory: InventoryReadBindingFactory,
        binding: InventoryReadBinding,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        native: WindowsControlProcess,
    ) -> None:
        self.factory, self.binding = factory, binding
        self.repository, self.journal, self.native = repository, journal, native
        self._issued: dict[CapturedInventoryRead, tuple[object, ...]] = {}
        self._slot_results: dict[tuple[int, str, str | None], CapturedInventoryRead] = {}
        try:
            self._core()
            key = (
                binding.execution_id,
                journal.owner.executor_generation,
                binding.parent_action_id,
            )
            current = _LIVE.get(key)
            if current is None:
                current = _LiveContext(
                    factory, binding, repository, journal, native, original_process._binary_sha()
                )
                _LIVE[key] = current
            if any(
                left is not right
                for left, right in (
                    (current.factory, factory),
                    (current.binding, binding),
                    (current.repository, repository),
                    (current.journal, journal),
                    (current.native, native),
                )
            ):
                raise _denied()
            self._live = current
            self._commands = InventoryCommands(binding, factory)
            self._owned()
        except Exception:
            raise _denied() from None

    @property
    def commands(self) -> InventoryCommands:
        return self._commands

    def _core(self) -> None:
        if (
            type(self.factory) is not InventoryReadBindingFactory
            or type(self.binding) is not InventoryReadBinding
            or type(self.native) is not WindowsControlProcess
            or type(self.journal) is not ProtectedControlJournal
            or self.factory.repository is not self.repository
            or self.factory.journal is not self.journal
            or self.journal.root != PROJECT_ROOT
        ):
            raise _denied()
        self.journal._owned()
        assert_origin: Callable[[InventoryReadBinding], object] = self.factory.assert_issued
        if assert_origin(self.binding) is not None:
            raise _denied()
        if (
            self.binding.execution_id != self.journal.owner.execution_id
            or self.binding.epoch_id != UUID(self.factory.epoch.binding.access_epoch_id)
        ):
            raise _denied()

    def _owned(self) -> None:
        self._core()
        if self._live.poisoned or original_process._binary_sha() != self._live.binary_sha:
            raise _denied()
        self.journal._owned()

    async def _state(self, parent: ReservedCutoverAction) -> None:
        self._owned()
        if (
            type(parent) is not ReservedCutoverAction
            or parent.action_id != self.binding.parent_action_id
            or parent.kind != _KINDS[self.binding.phase]
        ):
            raise _denied()
        self.journal._action_valid(parent)
        state = await self.repository.readback(self.factory.epoch.binding.claim)
        self._owned()
        self.factory._state(state, parent, _KINDS[self.binding.phase])
        prefix = tuple(
            (
                self._parent_signature(row.action),
                row.outcome,
                row.manifest_json,
                row.observed_at,
                row.event_sequence,
            )
            for row in state.actions[:-1]
        )
        if self._live.prefix is None:
            self._live.prefix = prefix
        elif self._live.prefix != prefix:
            raise _denied()
        self._owned()

    async def revalidate(self, parent: ReservedCutoverAction) -> None:
        """Fresh held-owner/DB guard for the later collection issuance boundary."""
        try:
            await self._state(parent)
        except Exception:
            raise _denied() from None

    def _base(self, parent: ReservedCutoverAction) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "epoch_id": str(self.binding.epoch_id),
            "execution_id": str(self.binding.execution_id),
            "phase": self.binding.phase,
            "binding_nonce": str(self.binding.nonce),
            "container_id": self.binding.container_id,
            "parent_action_id": str(parent.action_id),
            "parent_expected": parent.expected.identity_json,
            "parent_sequence": parent.sequence,
            "executor_generation": parent.executor_generation,
            "lock_session_id": str(self.journal.owner.session_id),
            "scope": self.journal.scope,
            "binary_sha256": self._live.binary_sha,
        }

    def _catalog_path(self, parent: ReservedCutoverAction) -> str:
        self.journal._action_valid(parent)
        return str(
            self.journal.root
            / ".local-data/access-epoch/private/control"
            / str(parent.execution_id)
            / f"{parent.action_id}.inventory-catalog.dpapi"
        )

    def _slot_path(self, parent: ReservedCutoverAction, helper: str, suffix: str) -> str:
        parsed = UUID(helper)
        if str(parsed) != helper or parsed.int == 0:
            raise _denied()
        return str(
            self.journal.root
            / ".local-data/access-epoch/private/control"
            / str(parent.execution_id)
            / f"{helper}.inventory-{suffix}.dpapi"
        )

    def _output_path(self, parent: ReservedCutoverAction, helper: str) -> str:
        return self._slot_path(parent, helper, "output")

    def _read_private(self, path: str) -> dict[str, Any] | None:
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
        packet = json.loads(raw, object_pairs_hook=_pairs)
        if type(packet) is not dict or canonical_json(packet).encode() != raw:
            raise _denied()
        return packet

    def _write_private(
        self, path: str, packet: dict[str, Any], previous: dict[str, Any] | None = None
    ) -> None:
        if not _same(self._read_private(path), previous):
            raise _denied()
        raw = canonical_json(packet).encode()
        if len(raw) > 1048576:
            raise _denied()
        encrypted = self.journal.protection.protect(raw)
        self._owned()
        if type(encrypted) is not bytes or not 0 < len(encrypted) <= 2097152:
            raise _denied()
        self.journal.files.write(path, encrypted)
        self._owned()
        if not _same(self._read_private(path), packet):
            raise _denied()

    def _catalog(self, parent: ReservedCutoverAction) -> dict[str, Any] | None:
        packet = self._read_private(self._catalog_path(parent))
        if packet is None:
            if self._live.initialized:
                raise _denied()
            return None
        if (
            self._live.catalog is None
            or canonical_json(packet).encode() != self._live.catalog
            or set(packet) != {"binding", "slots"}
            or not _same(packet["binding"], self._base(parent))
            or type(packet["slots"]) is not list
            or len(packet["slots"]) > _MAX_SLOTS
        ):
            raise _denied()
        for slot in packet["slots"]:
            if slot["complete"] is not True:
                raise _denied()
            self._capture(parent, slot)
        return packet

    def _target(self, parent: ReservedCutoverAction, command: InventoryCommand, round: int) -> str:
        return hashlib.sha256(
            canonical_json(
                {
                    "epoch_id": str(self.binding.epoch_id),
                    "execution_id": str(self.binding.execution_id),
                    "parent_action_id": str(parent.action_id),
                    "binding_nonce": str(self.binding.nonce),
                    "phase": self.binding.phase,
                    "round": round,
                    "purpose": command.purpose,
                    "index_name": command.index_name,
                }
            ).encode()
        ).hexdigest()

    def _helper(self, parent: ReservedCutoverAction, slot: dict[str, Any]) -> ReservedCutoverAction:
        return ReservedCutoverAction(
            UUID(slot["helper_id"]),
            parent.execution_id,
            parent.sequence,
            parent.kind,
            ControlExpectedIdentity(slot["expected"], parent.sequence - 1),
            parent.executor_generation,
        )

    def _capture_binding(
        self, parent: ReservedCutoverAction, slot: dict[str, Any], record: ControlSubmissionRecord
    ) -> dict[str, Any]:
        if record.child is None:
            raise _denied()
        return {
            "parent": self._base(parent),
            "helper_id": slot["helper_id"],
            "expected": slot["expected"],
            "round": slot["round"],
            "purpose": slot["purpose"],
            "index_name": slot["index_name"],
            "child": {
                "pid": record.child.pid,
                "creation_time": record.child.creation_time,
                "job_id": str(record.child.job_id),
            },
        }

    def _intent_binding(
        self, parent: ReservedCutoverAction, slot: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "parent": self._base(parent),
            **{
                key: slot[key]
                for key in ("helper_id", "expected", "round", "purpose", "index_name")
            },
        }

    def _capture(self, parent: ReservedCutoverAction, slot: dict[str, Any]) -> tuple[int, bytes]:
        helper_id = slot["helper_id"]
        signature = self._live.commands.get(helper_id)
        captured = self._live.captures.get(helper_id)
        record = self.journal.read(self._helper(parent, slot))
        if (
            signature is None
            or captured is None
            or record is None
            or record.state != "process_finished"
            or type(record.exit_code) is not int
            or record.exit_code != 0
            or record.child != captured[0]
        ):
            raise _denied()
        intent = self._read_private(self._slot_path(parent, helper_id, "command"))
        expected_intent = {
            "binding": self._intent_binding(parent, slot),
            "argv": list(signature[0]),
            "stdin": base64.b64encode(signature[1]).decode("ascii"),
        }
        if not _same(intent, expected_intent):
            raise _denied()
        packet = self._read_private(self._output_path(parent, helper_id))
        expected_capture = {
            "binding": self._capture_binding(parent, slot, record),
            "exit_code": captured[1],
            "stdout": base64.b64encode(captured[2]).decode("ascii"),
            "stderr": base64.b64encode(captured[3]).decode("ascii"),
        }
        if not _same(packet, expected_capture):
            raise _denied()
        return captured[1], captured[2]

    @staticmethod
    def _parent_signature(parent: ReservedCutoverAction) -> tuple[object, ...]:
        return (
            str(parent.action_id),
            str(parent.execution_id),
            parent.kind.value,
            parent.sequence,
            parent.executor_generation,
            parent.expected.identity_json,
            parent.expected.preceding_sequence,
        )

    @staticmethod
    def _signature(result: CapturedInventoryRead) -> tuple[object, ...]:
        if (
            type(result.parent) is not ReservedCutoverAction
            or type(result.round) is not int
            or type(result.phase) is not str
            or type(result.purpose) is not str
            or result.index_name is not None
            and type(result.index_name) is not str
            or type(result.private_body) is not bytes
        ):
            raise _denied()
        return (
            RecordedInventoryReads._parent_signature(result.parent),
            result.phase,
            result.round,
            result.purpose,
            result.index_name,
            result.private_body,
        )

    def _issue(
        self, parent: ReservedCutoverAction, command: InventoryCommand, round: int, body: bytes
    ) -> CapturedInventoryRead:
        self._owned()
        result = CapturedInventoryRead(
            parent, self.binding.phase, round, command.purpose, command.index_name, body
        )
        key = (round, command.purpose, command.index_name)
        previous = self._slot_results.get(key)
        if previous is not None:
            self.assert_issued(previous)
            if self._signature(previous) != self._signature(result):
                raise _denied()
            return previous
        self._issued[result] = self._signature(result)
        self._slot_results[key] = result
        return result

    async def read(
        self, parent: ReservedCutoverAction, command: InventoryCommand, round: int
    ) -> CapturedInventoryRead:
        token: ChildToken | None = None
        record: ControlSubmissionRecord | None = None
        helper_journal: ProtectedControlJournal | None = None
        touched = False
        try:
            self._owned()
            if self._live.running:
                raise _denied()
            self.commands.assert_issued(command)
            if (
                type(round) is not int
                or round not in {1, 2, 3}
                or command.purpose not in _PURPOSES
                or round == 3
                and command.purpose != "listing"
            ):
                raise _denied()
        except Exception:
            raise _denied() from None
        self._live.running = True
        try:
            await self._state(parent)
            self.commands.assert_issued(command)
            touched = True
            current = self._catalog(parent)
            slots = current["slots"] if current is not None else []
            for slot in slots:
                if (slot["round"], slot["purpose"], slot["index_name"]) == (
                    round,
                    command.purpose,
                    command.index_name,
                ):
                    if self._live.commands[slot["helper_id"]] != (
                        command.argv,
                        command.private_stdin,
                    ):
                        raise _denied()
                    code, stdout = self._capture(parent, slot)
                    body = self.commands.decode(command, InventoryResponse(code, stdout))
                    await self._state(parent)
                    return self._issue(parent, command, round, body)
            used = sum(slot["body_size"] for slot in slots)
            capture_size = sum(
                len(value[2]) + len(value[3]) for value in self._live.captures.values()
            )
            if (
                len(slots) >= _MAX_SLOTS
                or used + _MAX_BODY > _MAX_TOTAL_BODY
                or capture_size + 524288 > _MAX_CAPTURE_MEMORY
                or slots
                and round < slots[-1]["round"]
            ):
                raise _denied()
            helper_journal = ProtectedControlJournal(
                self.journal.root,
                self.journal.protection,
                self.journal.files,
                self.journal.lock,
                self.journal.owner,
                self.journal.scope,
            )
            ticket = helper_journal.prepare_expected(
                parent.kind, parent.sequence - 1, self._target(parent, command, round)
            )
            helper = ReservedCutoverAction(
                uuid4(),
                parent.execution_id,
                parent.sequence,
                parent.kind,
                ticket.expected,
                parent.executor_generation,
            )
            slot = {
                "round": round,
                "purpose": command.purpose,
                "index_name": command.index_name,
                "helper_id": str(helper.action_id),
                "expected": helper.expected.identity_json,
                "complete": False,
                "body_size": 0,
            }
            packet: dict[str, Any] = {"binding": self._base(parent), "slots": [*slots, slot]}
            self._live.initialized = True
            self._live.commands[slot["helper_id"]] = (command.argv, command.private_stdin)
            self._write_private(self._catalog_path(parent), packet, current)
            self._live.catalog = canonical_json(packet).encode()
            self._write_private(
                self._slot_path(parent, slot["helper_id"], "command"),
                {
                    "binding": self._intent_binding(parent, slot),
                    "argv": list(command.argv),
                    "stdin": base64.b64encode(command.private_stdin).decode("ascii"),
                },
            )
            await self._state(parent)
            self.commands.assert_issued(command)
            record = helper_journal.begin(helper, ticket)
            await self._state(parent)
            self.commands.assert_issued(command)
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
            await self._state(parent)
            self.commands.assert_issued(command)
            self.native.resume(token)
            # wait(), not resume(), writes the private pipe. Guard after resume.
            await self._state(parent)
            self.commands.assert_issued(command)
            result = self.native.wait(token, 45000)
            self._owned()
            if (
                result.child is not token.child
                or type(result.exit_code) is not int
                or type(result.stdout) is not bytes
                or type(result.stderr) is not bytes
                or len(result.stdout) > _MAX_BODY + 4
                or len(result.stdout) + len(result.stderr) > 524288
            ):
                raise _denied()
            await self._state(parent)
            self._live.captures[slot["helper_id"]] = (
                child,
                result.exit_code,
                result.stdout,
                result.stderr,
            )
            self._write_private(
                self._output_path(parent, slot["helper_id"]),
                {
                    "binding": self._capture_binding(parent, slot, record),
                    "exit_code": result.exit_code,
                    "stdout": base64.b64encode(result.stdout).decode("ascii"),
                    "stderr": base64.b64encode(result.stderr).decode("ascii"),
                },
            )
            record = helper_journal.process_finished(record, child, result.exit_code)
            closing, token = token, None
            self.native.close(closing)
            self._owned()
            code, stdout = self._capture(parent, slot)
            body = self.commands.decode(command, InventoryResponse(code, stdout))
            await self._state(parent)
            previous = json.loads(canonical_json(packet))
            slot.update(complete=True, body_size=len(body))
            self._write_private(self._catalog_path(parent), packet, previous)
            self._live.catalog = canonical_json(packet).encode()
            await self._state(parent)
            self._capture(parent, slot)
            return self._issue(parent, command, round, body)
        except BaseException as exc:
            if (
                helper_journal is not None
                and record is not None
                and record.state in {"intent", "process_created"}
            ):
                with suppress(BaseException):
                    helper_journal.unknown(record)
            if touched:
                self._live.poisoned = True
            if isinstance(exc, Exception):
                raise _denied() from None
            raise
        finally:
            if token is not None:
                with suppress(BaseException):
                    self.native.close(token)
            self._live.running = False

    def assert_issued(self, result: CapturedInventoryRead) -> None:
        try:
            self._owned()
            if type(result) is not CapturedInventoryRead or self._issued.get(
                result
            ) != self._signature(result):
                raise _denied()
        except Exception:
            raise _denied() from None
