from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Mapping
from contextlib import suppress
from pathlib import Path
from threading import Event

from ai_workshop.labs.rag.generation.codex_app_server_gate import IsolationObservation

_MAX_STDOUT_LINE_BYTES = 2 * 1024 * 1024
_MAX_STDERR_CAPTURE_BYTES = 64 * 1024
_MAX_MCP_PAGES = 20
_TERMINATE_GRACE_SECONDS = 0.15
_KILL_REAP_GRACE_SECONDS = 0.20
_DRAIN_GRACE_SECONDS = 0.15
_CLEANUP_TIMEOUT_SECONDS = (
    _TERMINATE_GRACE_SECONDS + _KILL_REAP_GRACE_SECONDS + _DRAIN_GRACE_SECONDS
)
_WINDOWS_DISPATCH_SLACK_SECONDS = 0.10


class _ProtocolFailure(Exception):
    pass


class CodexAppServerProbe:
    def __init__(
        self,
        *,
        command: tuple[str, ...],
        codex_home: Path,
        empty_cwd: Path,
        timeout_seconds: float,
    ) -> None:
        self._command = command
        self._codex_home = codex_home
        self._empty_cwd = empty_cwd
        self._timeout_seconds = timeout_seconds

    async def probe(self) -> IsolationObservation:
        if sys.platform == "win32":
            cancellation = Event()
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(_run_with_windows_proactor, self, cancellation),
                    timeout=(
                        self._timeout_seconds
                        + _CLEANUP_TIMEOUT_SECONDS
                        + _WINDOWS_DISPATCH_SLACK_SECONDS
                    ),
                )
            except (Exception, asyncio.CancelledError):
                cancellation.set()
                return _failed_observation()
        return await self._probe_once()

    async def _probe_once(self, cancellation: Event | None = None) -> IsolationObservation:
        if (
            not self._command
            or self._timeout_seconds <= 0
            or (cancellation is not None and cancellation.is_set())
        ):
            return _failed_observation()

        process: asyncio.subprocess.Process | None = None
        stderr_task: asyncio.Task[None] | None = None
        observation = _failed_observation()
        deadline = asyncio.get_running_loop().time() + self._timeout_seconds
        try:
            if cancellation is not None and cancellation.is_set():
                raise _ProtocolFailure
            self._codex_home.mkdir(parents=True, exist_ok=True)
            self._empty_cwd.mkdir(parents=True, exist_ok=True)
            if cancellation is not None and cancellation.is_set():
                raise _ProtocolFailure
            process = await _await_until(
                asyncio.create_subprocess_exec(
                    *self._command,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=self._empty_cwd,
                    env=self.build_minimal_environment(self._codex_home),
                    limit=_MAX_STDOUT_LINE_BYTES + 1,
                ),
                deadline,
            )
            if process.stderr is None:
                raise _ProtocolFailure
            stderr_task = asyncio.create_task(
                _drain_stream(process.stderr, _MAX_STDERR_CAPTURE_BYTES)
            )
            observation = await _await_until(self._collect_observation(process), deadline)
        except Exception:
            observation = _failed_observation()
        finally:
            cleanup_complete = False
            if process is not None:
                try:
                    await _cleanup_process(process, stderr_task)
                    cleanup_complete = True
                except (Exception, asyncio.CancelledError):
                    cleanup_complete = False
            elif stderr_task is not None:
                try:
                    cleanup_complete = await _finish_drain_tasks((stderr_task,), deadline)
                except (Exception, asyncio.CancelledError):
                    cleanup_complete = False
            else:
                cleanup_complete = True
            if not cleanup_complete:
                observation = _failed_observation()
        return observation

    @staticmethod
    def build_minimal_environment(codex_home: Path) -> dict[str, str]:
        environment = {"CODEX_HOME": str(codex_home)}
        for name in ("ComSpec", "PATHEXT", "PATH", "SystemRoot"):
            value = os.environ.get(name)
            if value is not None:
                environment[name] = value
        return environment

    async def _collect_observation(
        self, process: asyncio.subprocess.Process
    ) -> IsolationObservation:
        version = _version_from_initialize_result(
            await self._request(process, 1, "initialize", {"clientInfo": {"name": "ai-workshop"}})
        )
        await self._notify(process, "initialized", {})

        config = _validated_config(await self._request(process, 2, "config/read", {}))
        _as_mapping(await self._request(process, 3, "configRequirements/read", {}))
        mcp_count, next_request_id = await self._read_paginated_mcp(process, 4)
        skills = _item_count(await self._request(process, next_request_id, "skills/list", {}))
        hooks = _item_count(
            await self._request(process, next_request_id + 1, "hooks/list", {})
        )
        apps = _item_count(
            await self._request(process, next_request_id + 2, "app/installed", {})
        )

        features = _as_mapping(config["features"])
        return IsolationObservation(
            cli_version=version,
            config_read=True,
            requirements_read=True,
            effective_tool_inventory_read=False,
            forbidden_builtin_tool_count=None,
            shell_enabled=_exact_bool(features.get("shell")),
            web_enabled=_exact_bool(features.get("web")),
            apps_enabled=_exact_bool(features.get("apps")),
            plugins_enabled=_exact_bool(features.get("plugins")),
            multi_agent_enabled=_exact_bool(features.get("multi_agent")),
            mcp_callable_count=mcp_count,
            app_callable_count=apps,
            plugin_enabled_count=None,
            skill_enabled_count=skills,
            hook_enabled_count=hooks,
            approval_policy=_exact_string(config["approvalPolicy"]),
            sandbox_mode=_exact_string(config["sandboxMode"]),
        )

    async def _read_paginated_mcp(
        self, process: asyncio.subprocess.Process, request_id: int
    ) -> tuple[int, int]:
        count = 0
        cursor: str | None = None
        for page in range(_MAX_MCP_PAGES):
            params: dict[str, str] = {} if cursor is None else {"cursor": cursor}
            result = _as_mapping(
                await self._request(process, request_id, "mcpServerStatus/list", params)
            )
            count += _item_count(result)
            if "nextCursor" not in result:
                raise _ProtocolFailure
            cursor = _cursor(result["nextCursor"])
            request_id += 1
            if cursor is None:
                return count, request_id
            if page == _MAX_MCP_PAGES - 1:
                raise _ProtocolFailure
        raise _ProtocolFailure

    async def _request(
        self,
        process: asyncio.subprocess.Process,
        request_id: int,
        method: str,
        params: Mapping[str, object],
    ) -> object:
        await self._write_message(
            process,
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)},
        )
        while True:
            message = await self._read_message(process)
            response_id = message.get("id")
            if type(response_id) is not int:
                continue
            if response_id != request_id:
                continue
            if message.get("jsonrpc") != "2.0":
                raise _ProtocolFailure
            if "error" in message or "result" not in message:
                raise _ProtocolFailure
            return message["result"]

    async def _notify(
        self,
        process: asyncio.subprocess.Process,
        method: str,
        params: Mapping[str, object],
    ) -> None:
        await self._write_message(
            process, {"jsonrpc": "2.0", "method": method, "params": dict(params)}
        )

    async def _write_message(
        self, process: asyncio.subprocess.Process, message: Mapping[str, object]
    ) -> None:
        if process.stdin is None:
            raise _ProtocolFailure
        payload = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
        process.stdin.write(payload)
        await process.stdin.drain()

    async def _read_message(self, process: asyncio.subprocess.Process) -> dict[str, object]:
        if process.stdout is None:
            raise _ProtocolFailure
        try:
            line = await process.stdout.readuntil(b"\n")
        except (asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            raise _ProtocolFailure from None
        if len(line) > _MAX_STDOUT_LINE_BYTES:
            raise _ProtocolFailure
        try:
            decoded = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise _ProtocolFailure from None
        return _as_mapping(decoded)


def _as_mapping(value: object) -> dict[str, object]:
    if type(value) is not dict or not all(type(key) is str for key in value):
        raise _ProtocolFailure
    return value


def _version_from_initialize_result(value: object) -> str:
    result = _as_mapping(value)
    direct_version = _exact_string(result.get("version"))
    if direct_version is not None:
        return direct_version
    server_info = _as_mapping(result.get("serverInfo"))
    nested_version = _exact_string(server_info.get("version"))
    if nested_version is None:
        raise _ProtocolFailure
    return nested_version


def _validated_config(value: object) -> dict[str, object]:
    config = _as_mapping(value)
    features = _as_mapping(config.get("features"))
    for name in ("shell", "web", "apps", "plugins", "multi_agent"):
        if _exact_bool(features.get(name)) is None:
            raise _ProtocolFailure
    if _exact_string(config.get("approvalPolicy")) is None:
        raise _ProtocolFailure
    if _exact_string(config.get("sandboxMode")) is None:
        raise _ProtocolFailure
    return config


def _item_count(value: object) -> int:
    result = _as_mapping(value)
    items = result.get("items")
    if type(items) is not list:
        raise _ProtocolFailure
    return len(items)


def _cursor(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is str:
        return value
    raise _ProtocolFailure


def _exact_bool(value: object) -> bool | None:
    return value if type(value) is bool else None


def _exact_string(value: object) -> str | None:
    return value if type(value) is str else None


def _failed_observation() -> IsolationObservation:
    return IsolationObservation(
        cli_version="",
        config_read=False,
        requirements_read=False,
        effective_tool_inventory_read=False,
        forbidden_builtin_tool_count=None,
        shell_enabled=None,
        web_enabled=None,
        apps_enabled=None,
        plugins_enabled=None,
        multi_agent_enabled=None,
        mcp_callable_count=None,
        app_callable_count=None,
        plugin_enabled_count=None,
        skill_enabled_count=None,
        hook_enabled_count=None,
        approval_policy=None,
        sandbox_mode=None,
    )


async def _await_until[T](awaitable: Awaitable[T], deadline: float) -> T:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        raise TimeoutError
    return await asyncio.wait_for(awaitable, timeout=remaining)


async def _drain_stream(reader: asyncio.StreamReader, retained_limit: int) -> None:
    retained = bytearray()
    while chunk := await reader.read(64 * 1024):
        remaining = retained_limit - len(retained)
        if remaining > 0:
            retained.extend(chunk[:remaining])


async def _cleanup_process(
    process: asyncio.subprocess.Process, stderr_task: asyncio.Task[None] | None
) -> None:
    loop = asyncio.get_running_loop()
    overall_deadline = loop.time() + _CLEANUP_TIMEOUT_SECONDS
    stdout_task = (
        asyncio.create_task(_drain_stream(process.stdout, 0))
        if process.stdout is not None
        else None
    )
    try:
        if process.returncode is None:
            with suppress(ProcessLookupError, OSError):
                process.terminate()
            await _wait_for_process(
                process,
                min(overall_deadline, loop.time() + _TERMINATE_GRACE_SECONDS),
            )
        if process.returncode is None:
            with suppress(ProcessLookupError, OSError):
                process.kill()
            await _wait_for_process(
                process,
                min(overall_deadline, loop.time() + _KILL_REAP_GRACE_SECONDS),
            )
    finally:
        tasks = tuple(task for task in (stderr_task, stdout_task) if task is not None)
        drains_complete = await _finish_drain_tasks(
            tasks,
            min(overall_deadline, loop.time() + _DRAIN_GRACE_SECONDS),
        )
    if not drains_complete:
        raise _ProtocolFailure
    if process.returncode is None:
        raise _ProtocolFailure


async def _wait_for_process(process: asyncio.subprocess.Process, deadline: float) -> None:
    remaining = deadline - asyncio.get_running_loop().time()
    if remaining <= 0:
        return
    with suppress(TimeoutError, OSError, ProcessLookupError, ValueError):
        await asyncio.wait_for(process.wait(), timeout=remaining)


async def _finish_drain_tasks(
    tasks: tuple[asyncio.Task[None], ...], deadline: float
) -> bool:
    if not tasks:
        return True
    remaining = max(0.0, deadline - asyncio.get_running_loop().time())
    done, pending = await asyncio.wait(tasks, timeout=remaining)
    for task in pending:
        task.cancel()
    if pending:
        with suppress(TimeoutError, OSError, ValueError):
            await asyncio.wait_for(
                asyncio.gather(*pending, return_exceptions=True), timeout=0.05
            )
    complete = not pending
    for task in done:
        try:
            task.result()
        except (Exception, asyncio.CancelledError):
            complete = False
    return complete


def _run_with_windows_proactor(
    probe: CodexAppServerProbe, cancellation: Event
) -> IsolationObservation:
    if cancellation.is_set():
        return _failed_observation()
    loop = asyncio.ProactorEventLoop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(probe._probe_once(cancellation))
    finally:
        loop.close()
        asyncio.set_event_loop(None)
