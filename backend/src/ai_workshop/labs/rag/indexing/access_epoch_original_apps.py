"""Original launch source observation and protected, exact-object authorization.

No process is stopped here. Fixed source provenance cannot settle historical
controls. Existing-process retirement still verifies each captured lifetime on
its own held Windows handle.
"""

import base64
import hashlib
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from ai_workshop.infrastructure.local.process_retirement_windows import ProcessLifetime
from ai_workshop.infrastructure.local.windows_process import process_identity
from ai_workshop.labs.rag.indexing.access_epoch_app_retirement import AppRetirementAllowlist
from ai_workshop.labs.rag.indexing.access_epoch_process import ReservationReadPort
from ai_workshop.labs.rag.indexing.access_epoch_repository import AccessEpochReadback
from ai_workshop.labs.rag.indexing.access_epoch_submission import ProtectedControlJournal
from ai_workshop.labs.rag.indexing.access_epoch_types import PreparedAccessEpoch, canonical_json
from ai_workshop.labs.rag.indexing.alias_recovery_local_native import (
    CommandExecutor,
    FixedCommand,
    NativeCommandExecutor,
)
from ai_workshop.labs.rag.indexing.alias_recovery_local_wsl import command_tokens

PROJECT_ROOT = Path(__file__).absolute().parents[6]
_REPORT = "docs/worklogs/2026-10-08-rag-codex161-runtime-restoration.md"
_REPORT_SHA256 = "3ce9d22df1db4fdc7f97ee500929e30cd3f6572e67fcd7470480443c9e1a8464"
_PIDS = {"api": 29536, "api_launcher": 33656, "api_supervisor": 73132}
_START = datetime(2026, 10, 8, 0, 46, 23, tzinfo=UTC)
_SUPERVISOR_EXE = Path(
    "C:/Program Files/WindowsApps/Microsoft.PowerShell_7.6.6.0_arm64__8wekyb3d8bbwe/pwsh.exe"
)
_ARGS = (
    "-m",
    "uvicorn",
    "ai_workshop.main:app",
    "--loop",
    "ai_workshop.shared.asyncio_policy:create_selector_event_loop",
    "--host",
    "127.0.0.1",
    "--port",
    "18000",
)


def _denied() -> ValueError:
    return ValueError("original_application_source_denied")


def _script_template(root: Path) -> str:
    return "\n".join(
        (
            "$ErrorActionPreference = 'Stop'",
            f"Set-Location -LiteralPath '{root}'",
            "Get-ChildItem Env: | Where-Object { $_.Name -like 'AI_WORKSHOP_*' } "
            "| ForEach-Object {",
            "Remove-Item -LiteralPath ('Env:' + $_.Name)",
            "}",
            "Remove-Item -LiteralPath Env:TASK_REVIEW_PASSWORD -ErrorAction SilentlyContinue",
            f"$env:PYTHONPATH = '{root / 'backend/src'}'",
            "$env:PYTHONUTF8 = '1'",
            f"& '{root / 'backend/.venv/Scripts/python.exe'}' " + " ".join(_ARGS),
            "exit $LASTEXITCODE",
        )
    )


def validate_original_supervisor(raw: bytes, root: Path) -> None:
    if root != PROJECT_ROOT or type(raw) is not bytes or not 0 < len(raw) <= 16384:
        raise _denied()
    try:
        lines = tuple(line.strip() for line in raw.decode("utf-8-sig").splitlines())
        expected = tuple(line.strip() for line in _script_template(root).splitlines())
        if lines != expected:
            raise _denied()
    except Exception:
        raise _denied() from None


def _ordinary(path: Path, limit: int) -> bytes:
    if (
        not path.is_absolute()
        or ".." in path.parts
        or any(p.is_symlink() or p.is_junction() for p in (path, *path.parents))
    ):
        raise _denied()
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    if not 0 < len(value) <= limit:
        raise _denied()
    return value


def _at(value: object) -> datetime:
    if type(value) is not str:
        raise _denied()
    result = datetime.fromisoformat(value)
    if result.utcoffset() != timedelta(0):
        raise _denied()
    return result


def _filetime_at(value: str) -> datetime:
    if type(value) is not str or re.fullmatch(r"[1-9][0-9]{0,19}", value) is None:
        raise _denied()
    return datetime(1601, 1, 1, tzinfo=UTC) + timedelta(microseconds=int(value) // 10)


@dataclass(frozen=True, slots=True, eq=False)
class ObservedOriginalApplications:
    source_binding: UUID
    targets: tuple[tuple[str, ProcessLifetime], ...] = field(repr=False)
    private_source: bytes = field(repr=False)


class OriginalApplicationSourceReader:
    def __init__(
        self,
        executor: CommandExecutor | None = None,
        query: Callable[[int], tuple[str, Path]] = process_identity,
    ) -> None:
        self.executor, self.query = executor or NativeCommandExecutor(), query
        self._issued: dict[ObservedOriginalApplications, ObservedOriginalApplications] = {}

    async def _host(self) -> dict[str, Any]:
        value = json.loads(await self.executor.run(FixedCommand.HOST))
        if type(value) is not dict or type(value.get("processes")) is not list:
            raise _denied()
        return value

    def _selected(self, host: dict[str, Any]) -> tuple[dict[str, Any], ...]:
        rows = {}
        for row in host["processes"]:
            if type(row) is not dict or type(row.get("pid")) is not int or row["pid"] in rows:
                raise _denied()
            rows[row["pid"]] = row
            command = row.get("command")
            if command is None:
                if type(row.get("name")) is not str or re.fullmatch(
                    r"python(?:w|[0-9.]+)?\.exe", row["name"], re.IGNORECASE
                ):
                    raise _denied()
                continue
            if type(command) is not str or "ai_workshop.worker:celery_app" in command:
                raise _denied()
        selected = tuple(rows[pid] for pid in _PIDS.values())
        api, launcher, supervisor = selected
        python = PROJECT_ROOT / "backend/.venv/Scripts/python.exe"
        if (
            api["parent_pid"] != launcher["pid"]
            or launcher["parent_pid"] != supervisor["pid"]
            or tuple(command_tokens(api["command"])[1:]) != _ARGS
            or tuple(command_tokens(launcher["command"])[1:]) != _ARGS
            or Path(command_tokens(api["command"])[0]) != python
            or Path(command_tokens(launcher["command"])[0]) != python
            or Path(api["executable"]) != Path(getattr(sys, "_base_executable", sys.executable))
            or Path(launcher["executable"]) != python
            or Path(supervisor["executable"]) != _SUPERVISOR_EXE
            or not _START <= _at(api["created_at"]) < _START + timedelta(seconds=1)
            or not _START <= _at(launcher["created_at"]) < _START + timedelta(seconds=1)
            or not _at(supervisor["created_at"])
            <= _at(launcher["created_at"])
            <= _at(api["created_at"])
        ):
            raise _denied()
        listening = [
            r for r in host["tcp"] if r.get("local_port") == 18000 and r.get("state") == "Listen"
        ]
        if (
            len(listening) != 1
            or listening[0].get("pid") != api["pid"]
            or listening[0].get("local_address") != "127.0.0.1"
        ):
            raise _denied()
        front = host["frontend_tcp"]
        if (
            not front
            or {r.get("pid") for r in front} != {7824}
            or 7824 not in rows
            or 30272 not in rows
        ):
            raise _denied()
        if rows[7824]["parent_pid"] != 30272:
            raise _denied()
        return selected

    async def observe(self) -> ObservedOriginalApplications:
        try:
            report = _ordinary(PROJECT_ROOT / _REPORT, 65536)
            if hashlib.sha256(report).hexdigest() != _REPORT_SHA256:
                raise _denied()
            before = await self._host()
            rows = self._selected(before)
            supervisor = rows[2]
            args = command_tokens(supervisor["command"])
            if (
                len(args) != 5
                or [x.lower() for x in args[1:4]] != ["-noprofile", "-noninteractive", "-file"]
                or Path(args[0]) != Path(supervisor["executable"])
            ):
                raise _denied()
            script = Path(args[4])
            if (
                not script.is_relative_to(PROJECT_ROOT / ".local-data")
                or ".." in script.parts
                or script.anchor != PROJECT_ROOT.anchor
                or any(":" in part for part in script.parts[1:])
                or script.suffix.lower() != ".ps1"
            ):
                raise _denied()
            raw = _ordinary(script, 16384)
            validate_original_supervisor(raw, PROJECT_ROOT)
            targets = []
            for role, row in zip(_PIDS, rows, strict=True):
                created, executable = self.query(row["pid"])
                if _filetime_at(created) != _at(row["created_at"]) or executable != Path(
                    row["executable"]
                ):
                    raise _denied()
                targets.append((role, ProcessLifetime(row["pid"], created, executable)))
            after = await self._host()
            if (
                self._selected(after) != rows
                or before["frontend_tcp"] != after["frontend_tcp"]
                or _ordinary(script, 16384) != raw
                or _ordinary(PROJECT_ROOT / _REPORT, 65536) != report
            ):
                raise _denied()
            for _, lifetime in targets:
                if self.query(lifetime.pid) != (lifetime.creation_time, lifetime.executable):
                    raise _denied()
            private = canonical_json(
                {
                    "report": _REPORT,
                    "report_sha256": _REPORT_SHA256,
                    "script": str(script),
                    "script_source": base64.b64encode(raw).decode(),
                    "processes": list(rows),
                    "frontend": before["frontend_tcp"],
                }
            ).encode()
            value = ObservedOriginalApplications(uuid4(), tuple(targets), private)
            self._issued[value] = value
            return value
        except Exception:
            raise _denied() from None

    def assert_issued(self, value: ObservedOriginalApplications) -> None:
        if type(value) is not ObservedOriginalApplications or self._issued.get(value) is not value:
            raise _denied()


class OriginalApplicationAllowlistIssuer:
    def __init__(
        self,
        epoch: PreparedAccessEpoch,
        repository: ReservationReadPort,
        journal: ProtectedControlJournal,
        reader: OriginalApplicationSourceReader,
    ) -> None:
        self.epoch, self.repository, self.journal, self.reader = epoch, repository, journal, reader
        self._issued: dict[AppRetirementAllowlist, tuple[ObservedOriginalApplications, bytes]] = {}
        self._attempted = False
        self._owned()

    def _owned(self) -> None:
        self.journal._owned()
        if (
            type(self.reader) is not OriginalApplicationSourceReader
            or self.journal.root != PROJECT_ROOT
            or str(self.journal.owner.execution_id) != self.epoch.binding.execution_id
            or self.journal.scope
            != hashlib.sha256(
                json.dumps([self.epoch.original.daemon_sha256, "ai-workshop"]).encode()
            ).hexdigest()
        ):
            raise _denied()

    def _path(self) -> str:
        return str(
            PROJECT_ROOT
            / ".local-data/access-epoch/private/control"
            / self.epoch.binding.execution_id
            / "original-app-source.dpapi"
        )

    async def _state(self) -> AccessEpochReadback:
        self._owned()
        state = await self.repository.readback(self.epoch.binding.claim)
        self._owned()
        if (
            state.prepared != self.epoch
            or state.executor_generation != self.journal.owner.executor_generation
            or state.operation_state != "open"
            or state.gate_state != "frozen"
            or state.receipt is not None
            or state.phase != "prepared"
            or state.actions
        ):
            raise _denied()
        return state

    async def read_current(self) -> AppRetirementAllowlist:
        try:
            if self._attempted:
                raise _denied()
            self._attempted = True
            before = await self._state()
            source = await self.reader.observe()
            self._owned()
            self.reader.assert_issued(source)
            packet = canonical_json(
                {
                    "schema_version": 1,
                    "execution_id": self.epoch.binding.execution_id,
                    "epoch_id": self.epoch.binding.access_epoch_id,
                    "executor_generation": self.journal.owner.executor_generation,
                    "source_binding": str(source.source_binding),
                    "source": base64.b64encode(source.private_source).decode(),
                    "targets": [
                        {
                            "role": role,
                            "pid": p.pid,
                            "creation_time": p.creation_time,
                            "executable": str(p.executable),
                        }
                        for role, p in source.targets
                    ],
                }
            ).encode()
            if len(packet) > 524288 or self.journal.files.read(self._path()) is not None:
                raise _denied()
            self._owned()
            encrypted = self.journal.protection.protect(packet)
            self._owned()
            if type(encrypted) is not bytes or not encrypted or encrypted == packet:
                raise _denied()
            self.journal.files.write(self._path(), encrypted)
            self._owned()
            if self.journal.files.read(self._path()) != encrypted:
                raise _denied()
            self._owned()
            if self.journal.protection.unprotect(encrypted) != packet:
                raise _denied()
            self._owned()
            if await self._state() != before:
                raise _denied()
            value = AppRetirementAllowlist(
                uuid4(), source.source_binding, source.targets, ("worker", "beat")
            )
            self._issued[value] = (source, packet)
            self.assert_issued(value)
            return value
        except Exception:
            raise _denied() from None

    def assert_issued(self, value: AppRetirementAllowlist) -> None:
        try:
            self._owned()
            if type(value) is not AppRetirementAllowlist or value not in self._issued:
                raise _denied()
            source, packet = self._issued[value]
            self.reader.assert_issued(source)
            encrypted = self.journal.files.read(self._path())
            self._owned()
            if (
                encrypted is None
                or self.journal.protection.unprotect(encrypted) != packet
                or value.source_binding != source.source_binding
                or value.targets != source.targets
                or value.off_roles != ("worker", "beat")
            ):
                raise _denied()
            self._owned()
        except Exception:
            raise _denied() from None
