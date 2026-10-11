"""Retire only the reader-issued bootstrap accepting JVM, separately from old.

Local helpers are recorded before resume. Their exit cannot replace exact daemon
stop metadata or successful all-container enumeration after retirement.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ai_workshop.labs.rag.indexing import access_epoch_process as original_process
from ai_workshop.labs.rag.indexing.access_epoch_deployment import (
    DeploymentCommands,
    ObservedDeployment,
)
from ai_workshop.labs.rag.indexing.access_epoch_local import CUTOVER_ORDER
from ai_workshop.labs.rag.indexing.access_epoch_process import (
    RecordedOriginalControlProcess,
    ReservationReadPort,
)
from ai_workshop.labs.rag.indexing.access_epoch_repository import AccessEpochReadback
from ai_workshop.labs.rag.indexing.access_epoch_settlement import (
    _docker_time,
    _json,
    original_daemon_sha256,
)
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_types import (
    ControlSettlement,
    CutoverActionKind,
    PreparedAccessEpoch,
    ReservedCutoverAction,
    canonical_json,
    strict_utc,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
    DAEMON,
    DOCKER_EXE,
    ORIGINAL_IMAGE_ID,
)
from ai_workshop.labs.rag.indexing.alias_recovery_types import utc_text

if TYPE_CHECKING:
    from ai_workshop.infrastructure.local.control_process_windows import WindowsControlProcess

_PIPE = "npipe:////./pipe/dockerDesktopLinuxEngine"
_KINDS = {CutoverActionKind.STOP_BOOTSTRAP, CutoverActionKind.RETIRE_BOOTSTRAP}


def _denied() -> ValueError:
    return ValueError("cutover_bootstrap_retirement_denied")


def _binding(
    builder: DeploymentCommands, bootstrap: ObservedDeployment, epoch: PreparedAccessEpoch
) -> None:
    builder.assert_observed(bootstrap)
    if (
        builder.epoch != epoch
        or bootstrap.kind != CutoverActionKind.START_BOOTSTRAP
        or str(bootstrap.execution_id) != epoch.binding.execution_id
    ):
        raise _denied()


def bootstrap_control_target(
    epoch: PreparedAccessEpoch,
    kind: CutoverActionKind,
    builder: DeploymentCommands,
    bootstrap: ObservedDeployment,
) -> str:
    _binding(builder, bootstrap, epoch)
    if type(kind) is not CutoverActionKind or kind not in _KINDS:
        raise _denied()
    return hashlib.sha256(
        canonical_json(
            {
                "binary_sha256": original_process._binary_sha(),
                "daemon_sha256": epoch.original.daemon_sha256,
                "container_id": bootstrap.container_id,
                "kind": kind.value,
                "bootstrap_manifest_sha256": hashlib.sha256(
                    bootstrap.manifest_json.encode()
                ).hexdigest(),
                "endpoint": _PIPE,
            }
        ).encode()
    ).hexdigest()


class RecordedBootstrapRetirement(RecordedOriginalControlProcess):
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        native: WindowsControlProcess,
        root: Path,
        builder: DeploymentCommands,
        bootstrap: ObservedDeployment,
    ) -> None:
        self.builder, self.bootstrap = builder, bootstrap
        super().__init__(epoch, repository, journal, native, root)

    def _owned(self) -> None:
        super()._owned()
        _binding(self.builder, self.bootstrap, self.epoch)

    def _target(self, kind: CutoverActionKind) -> str:
        self._owned()
        return bootstrap_control_target(self.epoch, kind, self.builder, self.bootstrap)

    def _argv(self, kind: CutoverActionKind) -> tuple[str, ...]:
        self._owned()
        if type(kind) is not CutoverActionKind or kind not in _KINDS:
            raise _denied()
        suffix = (
            ("stop", "--time", "30", self.bootstrap.container_id)
            if kind == CutoverActionKind.STOP_BOOTSTRAP
            else ("rm", self.bootstrap.container_id)
        )
        return (DOCKER_EXE, "--host", _PIPE, *suffix)


class BootstrapDockerReadPort(Protocol):
    async def daemon(self) -> str: ...
    async def metadata(self) -> str: ...
    async def all_ids(self) -> str: ...


class FixedBootstrapDockerReads:
    def __init__(self, builder: DeploymentCommands, bootstrap: ObservedDeployment) -> None:
        _binding(builder, bootstrap, builder.epoch)
        self.builder, self.bootstrap = builder, bootstrap

    async def _run(self, suffix: tuple[str, ...]) -> str:
        _binding(self.builder, self.bootstrap, self.builder.epoch)
        process = await asyncio.create_subprocess_exec(
            DOCKER_EXE,
            "--host",
            _PIPE,
            *suffix,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=30)
            if process.returncode != 0 or len(stdout) > 1_048_576:
                raise _denied()
            return stdout.decode("utf-8", errors="strict").strip()
        except BaseException:
            if process.returncode is None:
                process.kill()
                await process.wait()
            raise

    async def daemon(self) -> str:
        return await self._run(("info", "--format", '{"id":{{json .ID}},"os":{{json .OSType}}}'))

    async def metadata(self) -> str:
        return await self._run(
            (
                "inspect",
                self.bootstrap.container_id,
                "--format",
                '{"container_id":{{json .Id}},"image_id":{{json .Image}},'
                '"running":{{json .State.Running}},"restarting":{{json .State.Restarting}},'
                '"dead":{{json .State.Dead}},"pid":{{json .State.Pid}},'
                '"started_at":{{json .State.StartedAt}},"finished_at":{{json .State.FinishedAt}}}',
            )
        )

    async def all_ids(self) -> str:
        return await self._run(("ps", "--all", "--no-trunc", "--format", "{{.ID}}"))


class BootstrapDaemonSettlement:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        builder: DeploymentCommands,
        bootstrap: ObservedDeployment,
        reads: BootstrapDockerReadPort,
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.epoch, self.repository, self.journal = epoch, repository, journal
        self.builder, self.bootstrap, self.reads, self.clock = builder, bootstrap, reads, clock

    def _owned(self) -> None:
        self.journal.lock.assert_owned(self.journal.owner)
        _binding(self.builder, self.bootstrap, self.epoch)
        if (
            str(self.journal.owner.execution_id) != self.epoch.binding.execution_id
            or self.epoch.original.daemon_sha256 != original_daemon_sha256()
            or hashlib.sha256(
                json.dumps([self.epoch.original.daemon_sha256, "ai-workshop"]).encode()
            ).hexdigest()
            != self.journal.lock.scope_sha256
        ):
            raise _denied()

    async def _state(self, action: ReservedCutoverAction) -> AccessEpochReadback:
        self._owned()
        state = await self.repository.readback(self.epoch.binding.claim)
        self._owned()
        if (
            type(action) is not ReservedCutoverAction
            or action.kind not in _KINDS
            or state.prepared != self.epoch
            or state.executor_generation != self.journal.owner.executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or not state.actions
            or state.actions[-1].action != action
            or state.actions[-1].outcome not in {"pending", "unknown"}
            or state.actions[-1].outcome == "pending"
            and (
                state.actions[-1].event_sequence != action.sequence
                or state.actions[-1].manifest_json is not None
            )
            or state.actions[-1].outcome == "unknown"
            and state.actions[-1].event_sequence <= action.sequence
            or tuple(x.action.kind for x in state.actions[:-1])
            != CUTOVER_ORDER[: CUTOVER_ORDER.index(action.kind)]
            or any(
                x.outcome != "settled"
                or x.action.executor_generation != action.executor_generation
                or x.action.execution_id != action.execution_id
                for x in state.actions[:-1]
            )
        ):
            raise _denied()
        starts = [
            x for x in state.actions[:-1] if x.action.kind == CutoverActionKind.START_BOOTSTRAP
        ]
        if (
            len(starts) != 1
            or starts[0].action.action_id != self.bootstrap.action_id
            or starts[0].manifest_json != self.bootstrap.manifest_json
        ):
            raise _denied()
        record = self.journal.read(action)
        if (
            record is None
            or record.state != "process_finished"
            or record.exit_code != 0
            or record.child is None
            or _json(action.expected.identity_json).get("target_sha256")
            != bootstrap_control_target(self.epoch, action.kind, self.builder, self.bootstrap)
        ):
            raise _denied()
        return state

    async def observe(self, action: ReservedCutoverAction) -> ControlSettlement:
        try:
            state = await self._state(action)
            self._owned()
            daemon = _json(await self.reads.daemon())
            self._owned()
            if daemon != {"id": DAEMON, "os": "linux"}:
                raise _denied()
            now = self.clock()
            if type(now) is not datetime or now.utcoffset() != timedelta(0):
                raise _denied()
            manifest: dict[str, object] = {
                "container_id": self.bootstrap.container_id,
                "daemon_sha256": self.epoch.original.daemon_sha256,
                "action_id": str(action.action_id),
                "sequence": action.sequence,
                "method": "exact_synchronous_command_and_terminal_readback",
            }
            if action.kind == CutoverActionKind.STOP_BOOTSTRAP:
                metadata = _json(await self.reads.metadata())
                self._owned()
                if (
                    set(metadata)
                    != {
                        "container_id",
                        "image_id",
                        "running",
                        "restarting",
                        "dead",
                        "pid",
                        "started_at",
                        "finished_at",
                    }
                    or metadata["container_id"] != self.bootstrap.container_id
                    or metadata["image_id"] != ORIGINAL_IMAGE_ID
                    or any(metadata[k] is not False for k in ("running", "restarting", "dead"))
                    or type(metadata["pid"]) is not int
                    or metadata["pid"] != 0
                    or metadata["started_at"]
                    != _json(self.bootstrap.manifest_json)["docker_started_at"]
                ):
                    raise _denied()
                finished = _docker_time(metadata["finished_at"], ceil=True)
                if not self.bootstrap.started_at <= finished <= now:
                    raise _denied()
                manifest.update(
                    finished_at=utc_text(finished),
                    started_at_docker=metadata["started_at"],
                    finished_at_docker=metadata["finished_at"],
                )
            else:
                stops = [
                    x
                    for x in state.actions[:-1]
                    if x.action.kind == CutoverActionKind.STOP_BOOTSTRAP
                ]
                if len(stops) != 1 or stops[0].manifest_json is None:
                    raise _denied()
                stop = _json(stops[0].manifest_json)
                if (
                    stop.get("container_id") != self.bootstrap.container_id
                    or stop.get("action_id") != str(stops[0].action.action_id)
                    or stop.get("daemon_sha256") != self.epoch.original.daemon_sha256
                    or stop.get("method") != "exact_synchronous_command_and_terminal_readback"
                    or not self.bootstrap.started_at
                    <= strict_utc(stop.get("finished_at"))
                    <= stops[0].observed_at
                    <= now
                ):
                    raise _denied()
                ids = (await self.reads.all_ids()).splitlines()
                self._owned()
                if (
                    len(ids) != len(set(ids))
                    or self.bootstrap.container_id in ids
                    or any(len(x) != 64 or any(c not in "0123456789abcdef" for c in x) for x in ids)
                ):
                    raise _denied()
                manifest.update(
                    retired_at=utc_text(now), stopped_action_id=str(stops[0].action.action_id)
                )
            fresh = await self._state(action)
            if fresh != state:
                raise _denied()
            return ControlSettlement(
                action.action_id,
                action.execution_id,
                action.executor_generation,
                "settled",
                canonical_json(manifest),
                now,
            )
        except Exception:
            raise _denied() from None
