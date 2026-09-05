from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import Any


def _line(payload: dict[str, Any]) -> None:
    print(json.dumps(payload), flush=True)


def _response(
    request_id: int,
    result: object,
    *,
    unrelated_numeric_id: bool = False,
    unexpected_jsonrpc_header: bool = False,
) -> None:
    _line({"method": "synthetic/notification", "params": {}})
    if unrelated_numeric_id:
        _line({"id": 900, "result": {}})
    response: dict[str, object] = {"id": request_id, "result": result}
    if unexpected_jsonrpc_header:
        response["jsonrpc"] = "2.0"
    _line(response)


def _read_request() -> dict[str, object]:
    return json.loads(sys.stdin.readline())


def _validate_request(request: dict[str, object], mcp_cursor: str | None) -> None:
    method = request.get("method")
    params = request.get("params")
    empty_cwd = os.getcwd()
    expected_by_method: dict[str, object] = {
        "config/read": {"includeLayers": True},
        "skills/list": {"cwds": [empty_cwd], "forceReload": True},
        "hooks/list": {"cwds": [empty_cwd]},
        "app/installed": {"forceRefresh": True},
    }
    if method == "configRequirements/read":
        if "params" in request:
            raise SystemExit(6)
        return
    if method == "mcpServerStatus/list":
        if params != {
            "cursor": mcp_cursor,
            "limit": 100,
            "detail": "toolsAndAuthOnly",
        }:
            raise SystemExit(6)
        return
    if expected_by_method.get(method) != params:
        raise SystemExit(6)


def _next_cursor(result: object) -> str | None:
    if type(result) is not dict:
        raise SystemExit(7)
    cursor = result.get("nextCursor")
    if cursor is None or type(cursor) is str:
        return cursor
    raise SystemExit(7)


def _initialize_result(scenario: str) -> dict[str, object]:
    result: dict[str, object] = {
        "codexHome": os.environ["CODEX_HOME"],
        "platformFamily": "windows",
        "platformOs": "windows",
        "userAgent": "synthetic-user-agent",
    }
    if scenario == "initialize-version-only":
        return {"version": "server-controlled-version"}
    if scenario == "initialize-wrong-home":
        result["codexHome"] = os.path.join(os.environ["CODEX_HOME"], "other")
    elif scenario == "initialize-invalid-codex-home":
        result["codexHome"] = 1
    elif scenario == "initialize-invalid-platform-family":
        result["platformFamily"] = False
    elif scenario == "initialize-invalid-platform-os":
        result["platformOs"] = []
    elif scenario == "initialize-invalid-user-agent":
        result["userAgent"] = None
    return result


def _mcp_status(tools: object) -> dict[str, object]:
    return {
        "authStatus": "unsupported",
        "name": "synthetic-server",
        "resourceTemplates": [],
        "resources": [],
        "tools": tools,
    }


def _skill_metadata(enabled: bool) -> dict[str, object]:
    return {
        "description": "Synthetic skill",
        "enabled": enabled,
        "name": "synthetic-skill",
        "path": os.path.join(os.getcwd(), "synthetic-skill", "SKILL.md"),
        "scope": "repo",
    }


def _hook_metadata(enabled: bool) -> dict[str, object]:
    return {
        "handlerType": "prompt",
        "currentHash": "synthetic-hash",
        "displayOrder": 0,
        "enabled": enabled,
        "eventName": "sessionStart",
        "isManaged": False,
        "key": "synthetic-hook",
        "source": "project",
        "sourcePath": os.path.join(os.getcwd(), "synthetic-hooks.json"),
        "timeoutSec": 1,
        "trustStatus": "trusted",
    }


def _skills_result(scenario: str, skills: list[object]) -> dict[str, object]:
    entry: dict[str, object] = {
        "cwd": os.getcwd(),
        "errors": [],
        "skills": skills,
    }
    if scenario == "skills-missing-cwd":
        return {"data": []}
    if scenario == "skills-wrong-cwd":
        entry["cwd"] = os.path.join(os.getcwd(), "wrong")
    elif scenario == "skills-duplicate-cwd":
        return {"data": [entry, dict(entry)]}
    elif scenario == "skills-discovery-error":
        entry["errors"] = [
            {
                "message": "synthetic discovery failure",
                "path": os.path.join(os.getcwd(), "broken-skill"),
            }
        ]
    elif scenario == "skills-missing-container":
        entry.pop("skills")
    return {"data": [entry]}


def _hooks_result(scenario: str, hooks: list[object]) -> dict[str, object]:
    entry: dict[str, object] = {
        "cwd": os.getcwd(),
        "errors": [],
        "hooks": hooks,
        "warnings": [],
    }
    if scenario == "hooks-missing-cwd":
        return {"data": []}
    if scenario == "hooks-wrong-cwd":
        entry["cwd"] = os.path.join(os.getcwd(), "wrong")
    elif scenario == "hooks-duplicate-cwd":
        return {"data": [entry, dict(entry)]}
    elif scenario == "hooks-discovery-error":
        entry["errors"] = [
            {
                "message": "synthetic discovery failure",
                "path": os.path.join(os.getcwd(), "broken-hook"),
            }
        ]
    elif scenario == "hooks-missing-container":
        entry.pop("warnings")
    return {"data": [entry]}


def _run(scenario: str) -> None:
    if sys.argv[-3:] != ["app-server", "--stdio", "--strict-config"]:
        raise SystemExit(2)

    initialize = _read_request()
    if (
        initialize.get("method") != "initialize"
        or initialize.get("id") != 1
        or "jsonrpc" in initialize
        or initialize.get("params")
        != {
            "clientInfo": {
                "name": "ai-workshop",
                "title": "AI Workshop",
                "version": "0.1.0",
            }
        }
    ):
        raise SystemExit(3)
    _response(
        1,
        _initialize_result(scenario),
        unrelated_numeric_id=scenario == "unrelated-numeric-id",
    )

    initialized = _read_request()
    if (
        initialized.get("method") != "initialized"
        or "id" in initialized
        or "jsonrpc" in initialized
        or initialized.get("params") != {}
    ):
        raise SystemExit(4)

    if scenario == "timeout":
        time.sleep(2)
        return

    responses = _responses(scenario)
    mcp_cursor: str | None = None
    for request_id, result in responses:
        request = _read_request()
        if request.get("id") != request_id or "jsonrpc" in request:
            raise SystemExit(5)
        _validate_request(request, mcp_cursor)
        if scenario == "rpc-error" and request_id == 2:
            _line({"id": 2, "error": {"code": -1}})
            return
        if scenario == "malformed-envelope" and request_id == 2:
            _line({"id": 2})
            continue
        if scenario == "wrong-id-type" and request_id == 2:
            _line({"id": True, "result": False})
        if scenario == "invalid-json" and request_id == 2:
            print("not-json", flush=True)
            return
        if scenario == "stderr-secret" and request_id == 2:
            print("secret=do-not-expose", file=sys.stderr, flush=True)
            return
        if scenario == "oversize-line" and request_id == 2:
            print("x" * (2 * 1024 * 1024 + 1), flush=True)
            return
        if scenario == "stderr-backpressure" and request_id == 2:
            sys.stderr.write("x" * (4 * 1024 * 1024))
            sys.stderr.flush()
        if scenario == "descendant-held-pipe" and request_id == 2:
            subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
            time.sleep(2)
            return
        if scenario == "requirements-null" and request_id == 3:
            _response(request_id, {"requirements": None})
            continue
        _response(
            request_id,
            result,
            unrelated_numeric_id=scenario == "unrelated-numeric-id",
            unexpected_jsonrpc_header=scenario == "unexpected-jsonrpc-header",
        )
        if request.get("method") == "mcpServerStatus/list":
            mcp_cursor = _next_cursor(result)


def _responses(scenario: str) -> list[tuple[int, object]]:
    features: dict[str, object] = {
        "shell_tool": False,
        "web_search": False,
        "apps": False,
        "plugins": False,
        "multi_agent": False,
    }
    config: dict[str, object] = {
        "features": features,
        "approval_policy": "never",
        "sandbox_mode": "read-only",
    }
    mcp_tools: dict[str, object] = {}
    skills: list[object] = []
    hooks: list[object] = []
    apps: list[object] = []
    if scenario == "mcp-callable":
        mcp_tools = {
            "synthetic": {"inputSchema": {"type": "object"}, "name": "synthetic"}
        }
    elif scenario == "app-callable":
        apps = [{"id": "synthetic", "enabled": True, "callable": True}]
    elif scenario == "app-missing-id":
        apps = [{"enabled": True, "callable": True}]
    elif scenario == "app-invalid-id":
        apps = [{"id": 1, "enabled": True, "callable": True}]
    elif scenario == "app-invalid-enabled":
        apps = [{"id": "synthetic", "enabled": 1, "callable": True}]
    elif scenario == "app-invalid-callable":
        apps = [{"id": "synthetic", "enabled": True, "callable": 1}]
    elif scenario == "app-invalid-runtime-name":
        apps = [
            {
                "id": "synthetic",
                "enabled": True,
                "callable": True,
                "runtimeName": 1,
            }
        ]
    elif scenario == "app-callable-disabled":
        apps = [{"id": "synthetic", "enabled": False, "callable": True}]
    elif scenario == "skill-enabled":
        skills = [_skill_metadata(True)]
    elif scenario == "skill-disabled":
        skills = [_skill_metadata(False)]
    elif scenario == "skill-malformed-metadata":
        malformed_skill = _skill_metadata(True)
        malformed_skill.pop("description")
        skills = [malformed_skill]
    elif scenario == "hook-enabled":
        hooks = [_hook_metadata(True)]
    elif scenario == "hook-disabled":
        hooks = [_hook_metadata(False)]
    elif scenario == "hook-malformed-metadata":
        malformed_hook = _hook_metadata(True)
        malformed_hook.pop("currentHash")
        hooks = [malformed_hook]
    elif scenario == "plugin-enabled-unknown":
        features["plugins"] = True
    elif scenario == "forbidden-feature-enabled":
        features["shell_tool"] = True
    elif scenario == "config-invalid-bool":
        features["shell_tool"] = 1
    elif scenario.startswith("config-missing-"):
        missing_feature = scenario.removeprefix("config-missing-").replace("-", "_")
        features.pop(missing_feature)
    elif scenario == "unsafe-sandbox":
        config["sandbox_mode"] = "workspace-write"
    mcp_status = _mcp_status(mcp_tools)
    if scenario == "mcp-missing-auth-status":
        mcp_status.pop("authStatus")
    elif scenario == "mcp-invalid-auth-status":
        mcp_status["authStatus"] = "invalid"
    elif scenario == "mcp-invalid-name":
        mcp_status["name"] = 1
    elif scenario == "mcp-invalid-resource-templates":
        mcp_status["resourceTemplates"] = {}
    elif scenario == "mcp-invalid-resources":
        mcp_status["resources"] = {}
    elif scenario == "mcp-invalid-tools":
        mcp_status["tools"] = []
    elif scenario == "mcp-tool-missing-input-schema":
        mcp_status["tools"] = {"synthetic": {"name": "synthetic"}}
    elif scenario == "mcp-tool-invalid-name":
        mcp_status["tools"] = {"synthetic": {"inputSchema": {}, "name": 1}}
    mcp_result: object = {"data": [mcp_status], "nextCursor": None}
    if scenario == "mcp-missing-terminal-cursor":
        mcp_result = {"data": [mcp_status]}
    elif scenario == "mcp-invalid-cursor":
        mcp_result = {"data": [mcp_status], "nextCursor": 1}
    if scenario == "wrong-count":
        mcp_result = {"data": False, "nextCursor": None}
    if scenario == "pagination-overflow":
        overflow_pages = [
            (item, {"data": [], "nextCursor": "more"}) for item in range(4, 25)
        ]
        return [(2, {"config": config, "origins": {}}), (3, {"requirements": {}}), *overflow_pages]
    if scenario == "twentieth-page-null":
        pages: list[tuple[int, object]] = []
        for request_id in range(4, 24):
            cursor = None if request_id == 23 else f"cursor-{request_id}"
            pages.append((request_id, {"data": [], "nextCursor": cursor}))
        return [
            (2, {"config": config, "origins": {}}),
            (3, {"requirements": {}}),
            *pages,
            (24, _skills_result(scenario, skills)),
            (25, _hooks_result(scenario, hooks)),
            (26, {"apps": apps}),
        ]
    return [
        (2, {"config": config, "origins": {}}),
        (3, {"requirements": {}}),
        (4, mcp_result),
        (5, _skills_result(scenario, skills)),
        (6, _hooks_result(scenario, hooks)),
        (7, {"apps": apps}),
    ]


if __name__ == "__main__":
    _run(sys.argv[1])
