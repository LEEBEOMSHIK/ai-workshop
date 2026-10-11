"""Recorded native route reads; a DTO or local Job exit is never route authority."""

import base64
import hashlib
import os
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from ai_workshop.infrastructure.local.control_process_windows import (
    ChildToken,
    WindowsControlProcess,
)
from ai_workshop.labs.rag.indexing.access_epoch_control_native import NativeControlContext, _freeze
from ai_workshop.labs.rag.indexing.access_epoch_deployment import PROJECT_ROOT
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_observations import RouteObservation
from ai_workshop.labs.rag.indexing.access_epoch_repository import AccessEpochReadback
from ai_workshop.labs.rag.indexing.access_epoch_route_commands import (
    _ROUTE_TEMPLATE_DIGEST,
    DecodedRouteProbe,
    NativeRouteCommands,
    PrivateRouteResponse,
    RouteCommand,
    RouteProbeKind,
    _load,
)
from ai_workshop.labs.rag.indexing.access_epoch_submission import (
    ControlProcessIdentity,
    ControlSubmissionRecord,
    FreshSubmissionTicket,
    ProtectedControlJournal,
)
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    CutoverActionKind,
    ReservedCutoverAction,
    canonical_json,
)

_MAX_CAPTURE = 1024 * 1024
_MAX_TOTAL = 16 * 1024 * 1024


def _denied() -> ValueError:
    return ValueError("native_route_process_unverified")


def _capture_response(
    output: Any, expected: dict[str, Any]
) -> tuple[PrivateRouteResponse, datetime]:
    """Validate private bytes, not their provenance or caller authority."""
    try:
        if (
            type(output) is not dict
            or set(output) != {"binding", "exit_code", "stdout", "stderr", "captured_at"}
            or type(output["binding"]) is not dict
            or canonical_json(output["binding"]) != canonical_json(expected)
            or type(output["exit_code"]) is not int
            or output["exit_code"] != 0
            or type(output["stdout"]) is not str
            or type(output["stderr"]) is not str
            or type(output["captured_at"]) is not str
        ):
            raise _denied()
        stdout, stderr = (
            base64.b64decode(output[name], validate=True) for name in ("stdout", "stderr")
        )
        if len(stdout) + len(stderr) > _MAX_CAPTURE or any(
            base64.b64encode(raw).decode() != output[name]
            for name, raw in (("stdout", stdout), ("stderr", stderr))
        ):
            raise _denied()
        captured_at = datetime.fromisoformat(output["captured_at"])
        if (
            captured_at.utcoffset() != timedelta(0)
            or captured_at.isoformat(timespec="microseconds") != output["captured_at"]
        ):
            raise _denied()
        return PrivateRouteResponse(0, stdout, stderr), captured_at
    except Exception:
        raise _denied() from None


@dataclass(frozen=True, slots=True, eq=False)
class VerifiedNativeRoutes:
    nonce: UUID
    parent_action_id: UUID
    routes: tuple[RouteObservation, ...]
    manifest_json: str
    observed_at: datetime


@dataclass(slots=True)
class _LiveRoutes:
    issuer: "RecordedNativeRoutes"
    parent: ReservedCutoverAction
    parent_signature: object
    attempted: bool = False
    poisoned: bool = False
    plans: tuple[
        tuple[RouteCommand, ProtectedControlJournal, ReservedCutoverAction, FreshSubmissionTicket],
        ...,
    ] = ()
    catalog: dict[str, Any] | None = None
    capture_signatures: dict[UUID, object] = field(default_factory=dict)


# Same live context/parent only. A new issuer cannot bypass a missing write ACK.
_LIVE: dict[tuple[NativeControlContext, UUID], _LiveRoutes] = {}


class RecordedNativeRoutes:
    def __init__(self, context: NativeControlContext, commands: NativeRouteCommands) -> None:
        if (
            type(context) is not NativeControlContext
            or type(commands) is not NativeRouteCommands
            or commands.context is not context
        ):
            raise _denied()
        context.assert_sources()
        self._context, self._commands = context, commands
        self._running = False
        self._issued: dict[VerifiedNativeRoutes, object] = {}

    @property
    def context(self) -> NativeControlContext:
        return self._context

    @property
    def commands(self) -> NativeRouteCommands:
        return self._commands

    def _guard(self) -> None:
        if self.commands.context is not self.context:
            raise _denied()
        self.commands._runtime()
        self.context.assert_owned()

    async def _state(self, parent: ReservedCutoverAction) -> AccessEpochReadback:
        self._guard()
        c = self.context
        state = await c.revalidate()
        self._guard()
        if (
            type(parent) is not ReservedCutoverAction
            or parent.kind != CutoverActionKind.VERIFY_ACCESS
            or state.phase != "secured_started"
            or len(state.actions) != len(CUTOVER_ORDER)
            or _freeze(state.actions[-1].action) != _freeze(parent)
            or state.actions[-1].outcome not in {"pending", "unknown"}
            or any(row.outcome != "settled" for row in state.actions[:-1])
            or c.held_owner is None
            or parent.execution_id != c.held_owner.execution_id
            or parent.executor_generation != c.held_owner.executor_generation
        ):
            raise _denied()
        sequence = 0
        for row in state.actions:
            a = row.action
            if (
                type(a.sequence) is not int
                or type(row.event_sequence) is not int
                or type(a.expected.preceding_sequence) is not int
                or a.sequence != sequence + 1
                or a.expected.preceding_sequence != sequence
                or row.outcome == "pending"
                and (row.manifest_json is not None or row.event_sequence != a.sequence)
                or row.outcome != "pending"
                and row.event_sequence <= a.sequence
            ):
                raise _denied()
            sequence = row.event_sequence
        state_signature = _freeze(state)
        factory, final = c.final_auth_factory, c.final
        assert factory is not None and final is not None
        current = await factory.create(final)
        self._guard()
        binding = self.commands._runtime()
        if (
            _freeze(current.keys) != _freeze(binding.keys)
            or _freeze(current.permissions) != _freeze(binding.permissions)
            or current.container_id != binding.container_id
            or current.epoch_id != binding.epoch_id
            or current.execution_id != binding.execution_id
        ):
            raise _denied()
        after = await c.revalidate()
        self._guard()
        if _freeze(after) != state_signature:
            raise _denied()
        return state

    def _path(self, parent: ReservedCutoverAction, suffix: str) -> str:
        return str(
            PROJECT_ROOT
            / ".local-data/access-epoch/private/control"
            / str(parent.execution_id)
            / suffix
        )

    def _catalog_path(self, parent: ReservedCutoverAction) -> str:
        return self._path(parent, str(parent.action_id) + ".routes.dpapi")

    def _read(self, path: str) -> dict[str, Any] | None:
        self._guard()
        journal = self.context.journal
        assert journal is not None
        encrypted = journal.files.read(path)
        self._guard()
        if encrypted is None:
            return None
        if type(encrypted) is not bytes or not 0 < len(encrypted) <= 2 * _MAX_CAPTURE:
            raise _denied()
        raw = journal.protection.unprotect(encrypted)
        self._guard()
        packet = _load(raw)
        if canonical_json(packet).encode() != raw:
            raise _denied()
        return packet

    def _write(self, path: str, value: dict[str, Any]) -> None:
        self._guard()
        journal = self.context.journal
        assert journal is not None
        packet = canonical_json(value).encode()
        if len(packet) > 2 * _MAX_CAPTURE:
            raise _denied()
        encrypted = journal.protection.protect(packet)
        self._guard()
        journal.files.write(path, encrypted)
        self._guard()
        readback = self._read(path)
        if readback is None or canonical_json(readback) != canonical_json(value):
            raise _denied()

    def _base(self, parent: ReservedCutoverAction) -> dict[str, Any]:
        self._guard()
        c = self.context
        assert c.final is not None and c.epoch is not None and c.held_owner is not None
        assert c.journal is not None
        return {
            "schema_version": 1,
            "kind": "native_seven_route_helpers",
            "parent_action_id": str(parent.action_id),
            "parent_expected_sha256": hashlib.sha256(
                parent.expected.identity_json.encode()
            ).hexdigest(),
            "epoch_id": c.epoch.binding.access_epoch_id,
            "execution_id": str(parent.execution_id),
            "executor_generation": parent.executor_generation,
            "sequence": parent.sequence,
            "final_container_id": c.final.container_id,
            "final_action_id": str(c.final.action_id),
            "final_manifest_sha256": hashlib.sha256(c.final.manifest_json.encode()).hexdigest(),
            "scope_sha256": c.journal.scope,
            "session_id": str(c.held_owner.session_id),
            "template_sha256": _ROUTE_TEMPLATE_DIGEST,
        }

    def _plans(self, parent: ReservedCutoverAction) -> _LiveRoutes:
        self._guard()
        c = self.context
        journal = c.journal
        assert journal is not None
        key = c, parent.action_id
        if key in _LIVE:
            live = _LIVE[key]
            if live.issuer is not self or live.parent_signature != _freeze(parent) or live.poisoned:
                raise _denied()
            return live
        live = _LiveRoutes(self, parent, _freeze(parent))
        _LIVE[key] = live  # Claim before any issuance or I/O; failures cannot mint a new nonce.
        try:
            plans = []
            base = self._base(parent)
            for purpose in RouteProbeKind:
                command = self.commands.command(purpose)
                helper = ProtectedControlJournal(
                    journal.root,
                    journal.protection,
                    journal.files,
                    journal.lock,
                    journal.owner,
                    journal.scope,
                )
                ticket = helper.prepare_expected(
                    CutoverActionKind.VERIFY_ACCESS,
                    0,
                    hashlib.sha256(
                        canonical_json({**base, "purpose": purpose.value}).encode()
                    ).hexdigest(),
                )
                action = ReservedCutoverAction(
                    uuid4(),
                    parent.execution_id,
                    1,
                    CutoverActionKind.VERIFY_ACCESS,
                    ticket.expected,
                    parent.executor_generation,
                )
                plans.append((command, helper, action, ticket))
            live.plans = tuple(plans)
            live.catalog = {
                **base,
                "steps": [
                    {
                        "purpose": cmd.purpose.value,
                        "action_id": str(action.action_id),
                        "expected_sha256": hashlib.sha256(
                            action.expected.identity_json.encode()
                        ).hexdigest(),
                        "submission_id": str(ticket.submission_id),
                    }
                    for cmd, _, action, ticket in plans
                ],
            }
            return live
        except BaseException:
            live.poisoned = True
            raise

    def _capture_binding(
        self, parent: ReservedCutoverAction, command: RouteCommand, record: ControlSubmissionRecord
    ) -> dict[str, Any]:
        if record.child is None:
            raise _denied()
        return {
            **self._base(parent),
            "purpose": command.purpose.value,
            "helper_action_id": str(record.action.action_id),
            "submission_id": str(record.submission_id),
            "helper_expected_sha256": hashlib.sha256(
                record.action.expected.identity_json.encode()
            ).hexdigest(),
            "child": {
                "pid": record.child.pid,
                "creation_time": record.child.creation_time,
                "job_id": str(record.child.job_id),
            },
        }

    async def _recover(
        self, parent: ReservedCutoverAction, live: _LiveRoutes
    ) -> VerifiedNativeRoutes:
        state = await self._state(parent)
        state_signature = _freeze(state)
        if (
            live.issuer is not self
            or live.parent_signature != _freeze(parent)
            or live.catalog is None
        ):
            raise _denied()
        catalog = self._read(self._catalog_path(parent))
        if catalog is None or canonical_json(catalog) != canonical_json(live.catalog):
            raise _denied()
        probes: list[DecodedRouteProbe] = []
        sample_times: list[datetime] = []
        total = 0
        for command, journal, helper, _ in live.plans:
            await self._state(parent)
            record = journal.read(helper)
            if (
                record is None
                or record.state != "process_finished"
                or type(record.exit_code) is not int
                or record.exit_code != 0
                or record.child is None
            ):
                raise _denied()
            output = self._read(self._path(parent, str(helper.action_id) + ".route-output.dpapi"))
            if output is None or live.capture_signatures.get(helper.action_id) != _freeze(output):
                raise _denied()
            response, captured_at = _capture_response(
                output, self._capture_binding(parent, command, record)
            )
            sample_times.append(captured_at)
            total += len(response.stdout) + len(response.stderr)
            if total > _MAX_TOTAL:
                raise _denied()
            probes.append(self.commands.decode(command, response))
        if len(probes) != 27:
            raise _denied()
        start = state.actions[CUTOVER_ORDER.index(CutoverActionKind.START_SECURED)].action
        now = datetime.now(UTC)
        if (
            now < state.actions[-1].observed_at
            or sample_times != sorted(sample_times)
            or sample_times[-1] > now
        ):
            raise _denied()
        routes, manifest = self.commands._assemble(
            start, tuple(probes), now, sample_times[0], sample_times[-1]
        )
        final_state = await self._state(parent)
        if _freeze(final_state) != state_signature:
            raise _denied()
        cap = VerifiedNativeRoutes(uuid4(), parent.action_id, routes, manifest, now)
        self._issued[cap] = _freeze(cap)
        self._guard()
        return cap

    async def observe(self, parent: ReservedCutoverAction) -> VerifiedNativeRoutes:
        if self._running:
            raise _denied()
        self._running = True
        token: ChildToken | None = None
        cleanup_native: WindowsControlProcess | None = None
        active_journal: ProtectedControlJournal | None = None
        record: ControlSubmissionRecord | None = None
        try:
            state = await self._state(parent)
            live = self._plans(parent)
            if live.attempted:
                return await self._recover(parent, live)
            if state.actions[-1].outcome != "pending":
                raise _denied()
            live.attempted = True
            assert live.catalog is not None
            # A pre-existing catalog is not a ticket to recreate its helpers.
            if self._read(self._catalog_path(parent)) is not None:
                raise _denied()
            self._write(self._catalog_path(parent), live.catalog)
            total = 0
            for command, helper_journal, helper, ticket in live.plans:
                await self._state(parent)
                self.commands.assert_command(command)
                active_journal = helper_journal
                record = helper_journal.begin(helper, ticket)
                await self._state(parent)
                native = self.context.native
                assert native is not None
                cleanup_native = native
                environment = {
                    key: value
                    for key, value in os.environ.items()
                    if key.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATHEXT"}
                }
                self.commands.assert_command(command)
                token = native.create_suspended(
                    command.argv, environment, PROJECT_ROOT, stdin=command.private_stdin
                )
                child = ControlProcessIdentity(
                    token.child.pid, token.child.creation_time, token.child.job_id
                )
                record = helper_journal.process_created(record, child)
                await self._state(parent)
                self.commands.assert_command(command)
                native.resume(token)
                await self._state(parent)  # Native wait transmits private stdin.
                self.commands.assert_command(command)
                result = native.wait(token, 45000)
                captured_at = datetime.now(UTC)
                self._guard()
                if (
                    result.child is not token.child
                    or type(result.exit_code) is not int
                    or type(result.stdout) is not bytes
                    or type(result.stderr) is not bytes
                    or len(result.stdout) + len(result.stderr) > _MAX_CAPTURE
                ):
                    raise _denied()
                total += len(result.stdout) + len(result.stderr)
                if total > _MAX_TOTAL:
                    raise _denied()
                await self._state(parent)
                private_capture = {
                    "binding": self._capture_binding(parent, command, record),
                    "exit_code": result.exit_code,
                    "stdout": base64.b64encode(result.stdout).decode(),
                    "stderr": base64.b64encode(result.stderr).decode(),
                    "captured_at": captured_at.isoformat(timespec="microseconds"),
                }
                live.capture_signatures[helper.action_id] = _freeze(private_capture)
                self._write(
                    self._path(parent, str(helper.action_id) + ".route-output.dpapi"),
                    private_capture,
                )
                record = helper_journal.process_finished(record, child, result.exit_code)
                closing, token = token, None
                native.close(closing)
                self._guard()
                self.commands.decode(
                    command, PrivateRouteResponse(result.exit_code, result.stdout, result.stderr)
                )
                record = None
            return await self._recover(parent, live)
        except BaseException as exc:
            if (
                active_journal is not None
                and record is not None
                and record.state in {"intent", "process_created"}
            ):
                with suppress(BaseException):
                    active_journal.unknown(record)
            if isinstance(exc, Exception):
                raise _denied() from None
            raise
        finally:
            if token is not None and cleanup_native is not None:
                with suppress(BaseException):
                    cleanup_native.close(token)
            self._running = False

    def assert_issued(self, value: VerifiedNativeRoutes) -> None:
        try:
            self._guard()
            if type(value) is not VerifiedNativeRoutes or self._issued.get(value) != _freeze(value):
                raise _denied()
        except Exception:
            raise _denied() from None
