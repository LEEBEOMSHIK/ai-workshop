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
_MCP_AUTH_STATUSES = frozenset(
    {"unknown", "unsupported", "notLoggedIn", "bearerToken", "oAuth"}
)
_SKILL_SCOPES = frozenset({"user", "repo", "system", "admin"})
_HOOK_EVENT_NAMES = frozenset(
    {
        "preToolUse",
        "permissionRequest",
        "postToolUse",
        "preCompact",
        "postCompact",
        "sessionStart",
        "sessionEnd",
        "userPromptSubmit",
        "subagentStart",
        "subagentStop",
        "stop",
        "interrupt",
    }
)
_HOOK_SOURCES = frozenset(
    {
        "system",
        "user",
        "project",
        "mdm",
        "sessionFlags",
        "plugin",
        "cloudRequirements",
        "cloudManagedConfig",
        "legacyManagedConfigFile",
        "legacyManagedConfigMdm",
        "unknown",
    }
)
_HOOK_TRUST_STATUSES = frozenset({"managed", "untrusted", "trusted", "modified"})


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
        cli_version: str,
    ) -> None:
        self._command = command
        self._codex_home = codex_home
        self._empty_cwd = empty_cwd
        self._timeout_seconds = timeout_seconds
        self._cli_version = cli_version

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
                return _failed_observation(self._cli_version)
        return await self._probe_once()

    async def _probe_once(self, cancellation: Event | None = None) -> IsolationObservation:
        if (
            not self._command
            or self._timeout_seconds <= 0
            or (cancellation is not None and cancellation.is_set())
        ):
            return _failed_observation(self._cli_version)

        process: asyncio.subprocess.Process | None = None
        stderr_task: asyncio.Task[None] | None = None
        observation = _failed_observation(self._cli_version)
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
            observation = _failed_observation(self._cli_version)
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
                observation = _failed_observation(self._cli_version)
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
        _validated_initialize_result(
            await self._request(
                process,
                1,
                "initialize",
                {
                    "clientInfo": {
                        "name": "ai-workshop",
                        "title": "AI Workshop",
                        "version": "0.1.0",
                    }
                },
            ),
            self._codex_home,
        )
        await self._notify(process, "initialized", {})

        config = _validated_config(
            await self._request(process, 2, "config/read", {"includeLayers": True})
        )
        _validated_requirements(
            await self._request(process, 3, "configRequirements/read", None)
        )
        mcp_count, next_request_id = await self._read_paginated_mcp(process, 4)
        skills = _enabled_skills_count(
            await self._request(
                process,
                next_request_id,
                "skills/list",
                {"cwds": [str(self._empty_cwd)], "forceReload": True},
            ),
            self._empty_cwd,
        )
        hooks = _enabled_hooks_count(
            await self._request(
                process,
                next_request_id + 1,
                "hooks/list",
                {"cwds": [str(self._empty_cwd)]},
            ),
            self._empty_cwd,
        )
        apps = _callable_apps_count(
            await self._request(
                process, next_request_id + 2, "app/installed", {"forceRefresh": True}
            )
        )

        features = _as_mapping(config["features"])
        return IsolationObservation(
            cli_version=self._cli_version,
            config_read=True,
            requirements_read=True,
            effective_tool_inventory_read=False,
            forbidden_builtin_tool_count=None,
            shell_enabled=_exact_bool(features.get("shell_tool")),
            web_enabled=_exact_bool(features.get("web_search")),
            apps_enabled=_exact_bool(features.get("apps")),
            plugins_enabled=_exact_bool(features.get("plugins")),
            multi_agent_enabled=_exact_bool(features.get("multi_agent")),
            mcp_callable_count=mcp_count,
            app_callable_count=apps,
            plugin_enabled_count=None,
            skill_enabled_count=skills,
            hook_enabled_count=hooks,
            approval_policy=_exact_string(config["approval_policy"]),
            sandbox_mode=_normalized_sandbox_mode(config["sandbox_mode"]),
        )

    async def _read_paginated_mcp(
        self, process: asyncio.subprocess.Process, request_id: int
    ) -> tuple[int, int]:
        count = 0
        cursor: str | None = None
        for page in range(_MAX_MCP_PAGES):
            params: dict[str, object] = {
                "cursor": cursor,
                "limit": 100,
                "detail": "toolsAndAuthOnly",
            }
            result = _as_mapping(
                await self._request(process, request_id, "mcpServerStatus/list", params)
            )
            count += _mcp_callable_tool_count(result)
            cursor = _cursor(result.get("nextCursor"))
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
        params: Mapping[str, object] | None,
    ) -> object:
        request: dict[str, object] = {"id": request_id, "method": method}
        if params is not None:
            request["params"] = dict(params)
        await self._write_message(process, request)
        while True:
            message = await self._read_message(process)
            response_id = message.get("id")
            if type(response_id) is not int:
                continue
            if response_id != request_id:
                continue
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
            process, {"method": method, "params": dict(params)}
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


def _validated_initialize_result(value: object, expected_codex_home: Path) -> None:
    result = _as_mapping(value)
    codex_home = _exact_string(result.get("codexHome"))
    if codex_home is None or Path(codex_home) != expected_codex_home:
        raise _ProtocolFailure
    for name in ("platformFamily", "platformOs", "userAgent"):
        if _exact_string(result.get(name)) is None:
            raise _ProtocolFailure


def _validated_config(value: object) -> dict[str, object]:
    response = _as_mapping(value)
    config = _as_mapping(response.get("config"))
    features = _as_mapping(config.get("features"))
    for name in ("shell_tool", "web_search", "apps", "plugins", "multi_agent"):
        if _exact_bool(features.get(name)) is None:
            raise _ProtocolFailure
    if _exact_string(config.get("approval_policy")) is None:
        raise _ProtocolFailure
    if _exact_string(config.get("sandbox_mode")) is None:
        raise _ProtocolFailure
    return config


def _validated_requirements(value: object) -> None:
    result = _as_mapping(value)
    _as_mapping(result.get("requirements"))


def _mcp_callable_tool_count(value: object) -> int:
    result = _as_mapping(value)
    data = _list_from_mapping(result, "data")
    count = 0
    for raw_status in data:
        status = _as_mapping(raw_status)
        if status.get("authStatus") not in _MCP_AUTH_STATUSES:
            raise _ProtocolFailure
        if _exact_string(status.get("name")) is None:
            raise _ProtocolFailure
        _list_from_mapping(status, "resourceTemplates")
        _list_from_mapping(status, "resources")
        tools = _as_mapping(status.get("tools"))
        for raw_tool in tools.values():
            tool = _as_mapping(raw_tool)
            if "inputSchema" not in tool:
                raise _ProtocolFailure
            if _exact_string(tool.get("name")) is None:
                raise _ProtocolFailure
        count += len(tools)
    return count


def _enabled_skills_count(value: object, expected_cwd: Path) -> int:
    metadata_items, _ = _validated_discovery_entry(value, "skills", expected_cwd)
    count = 0
    for raw_metadata in metadata_items:
        metadata = _as_mapping(raw_metadata)
        for name in ("description", "name", "path"):
            if _exact_string(metadata.get(name)) is None:
                raise _ProtocolFailure
        if metadata.get("scope") not in _SKILL_SCOPES:
            raise _ProtocolFailure
        enabled = _exact_bool(metadata.get("enabled"))
        if enabled is None:
            raise _ProtocolFailure
        if enabled:
            count += 1
    return count


def _enabled_hooks_count(value: object, expected_cwd: Path) -> int:
    metadata_items, entry = _validated_discovery_entry(value, "hooks", expected_cwd)
    warnings = _list_from_mapping(entry, "warnings")
    if any(_exact_string(warning) is None for warning in warnings):
        raise _ProtocolFailure
    count = 0
    for raw_metadata in metadata_items:
        metadata = _as_mapping(raw_metadata)
        _validate_hook_metadata(metadata)
        if metadata["enabled"] is True:
            count += 1
    return count


def _validated_discovery_entry(
    value: object, field: str, expected_cwd: Path
) -> tuple[list[object], dict[str, object]]:
    result = _as_mapping(value)
    entries = _list_from_mapping(result, "data")
    if len(entries) != 1:
        raise _ProtocolFailure
    entry = _as_mapping(entries[0])
    if _exact_string(entry.get("cwd")) != str(expected_cwd):
        raise _ProtocolFailure
    if _list_from_mapping(entry, "errors"):
        raise _ProtocolFailure
    return _list_from_mapping(entry, field), entry


def _validate_hook_metadata(metadata: dict[str, object]) -> None:
    for name in ("currentHash", "key", "sourcePath"):
        if _exact_string(metadata.get(name)) is None:
            raise _ProtocolFailure
    if type(metadata.get("displayOrder")) is not int:
        raise _ProtocolFailure
    if _exact_bool(metadata.get("enabled")) is None:
        raise _ProtocolFailure
    if metadata.get("eventName") not in _HOOK_EVENT_NAMES:
        raise _ProtocolFailure
    if _exact_bool(metadata.get("isManaged")) is None:
        raise _ProtocolFailure
    if metadata.get("source") not in _HOOK_SOURCES:
        raise _ProtocolFailure
    timeout_seconds = metadata.get("timeoutSec")
    if type(timeout_seconds) is not int or timeout_seconds < 0:
        raise _ProtocolFailure
    if metadata.get("trustStatus") not in _HOOK_TRUST_STATUSES:
        raise _ProtocolFailure
    handler_type = _exact_string(metadata.get("handlerType"))
    if handler_type == "command":
        if _exact_string(metadata.get("command")) is None:
            raise _ProtocolFailure
    elif handler_type == "mcpTool":
        if any(
            _exact_string(metadata.get(name)) is None for name in ("server", "tool")
        ):
            raise _ProtocolFailure
    elif handler_type not in {"prompt", "agent"}:
        raise _ProtocolFailure


def _callable_apps_count(value: object) -> int:
    result = _as_mapping(value)
    count = 0
    for app in _list_from_mapping(result, "apps"):
        app_state = _as_mapping(app)
        if _exact_string(app_state.get("id")) is None:
            raise _ProtocolFailure
        enabled = _exact_bool(app_state.get("enabled"))
        callable_app = _exact_bool(app_state.get("callable"))
        if enabled is None or callable_app is None:
            raise _ProtocolFailure
        runtime_name = app_state.get("runtimeName")
        if (
            "runtimeName" in app_state
            and runtime_name is not None
            and _exact_string(runtime_name) is None
        ):
            raise _ProtocolFailure
        if callable_app and not enabled:
            raise _ProtocolFailure
        if callable_app:
            count += 1
    return count


def _list_from_mapping(mapping: dict[str, object], field: str) -> list[object]:
    values = mapping.get(field)
    if type(values) is not list:
        raise _ProtocolFailure
    return values


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


def _normalized_sandbox_mode(value: object) -> str | None:
    return "readOnly" if value == "read-only" else None


def _failed_observation(cli_version: str) -> IsolationObservation:
    return IsolationObservation(
        cli_version=cli_version,
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
        return _failed_observation(probe._cli_version)
    loop = asyncio.ProactorEventLoop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(probe._probe_once(cancellation))
    finally:
        loop.close()
        asyncio.set_event_loop(None)
