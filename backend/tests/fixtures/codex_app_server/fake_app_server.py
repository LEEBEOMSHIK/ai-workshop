from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Any


def _line(payload: dict[str, Any]) -> None:
    print(json.dumps(payload), flush=True)


def _response(request_id: int, result: object, *, unrelated_numeric_id: bool = False) -> None:
    _line({"jsonrpc": "2.0", "method": "synthetic/notification", "params": {}})
    if unrelated_numeric_id:
        _line({"jsonrpc": "2.0", "id": 900, "result": {}})
    _line({"jsonrpc": "2.0", "id": request_id, "result": result})


def _read_request() -> dict[str, object]:
    return json.loads(sys.stdin.readline())


def _run(scenario: str) -> None:
    if sys.argv[-3:] != ["app-server", "--stdio", "--strict-config"]:
        raise SystemExit(2)

    initialize = _read_request()
    if initialize.get("method") != "initialize" or initialize.get("id") != 1:
        raise SystemExit(3)
    _response(
        1,
        {"version": "0.151.0"},
        unrelated_numeric_id=scenario == "unrelated-numeric-id",
    )

    initialized = _read_request()
    if initialized.get("method") != "initialized" or "id" in initialized:
        raise SystemExit(4)

    if scenario == "timeout":
        time.sleep(2)
        return

    responses = _responses(scenario)
    for request_id, result in responses:
        request = _read_request()
        if request.get("id") != request_id:
            raise SystemExit(5)
        if scenario == "rpc-error" and request_id == 2:
            _line({"jsonrpc": "2.0", "id": 2, "error": {"code": -1}})
            return
        if scenario == "malformed-envelope" and request_id == 2:
            _line({"id": 2, "result": result})
            continue
        if scenario == "wrong-id-type" and request_id == 2:
            _line({"jsonrpc": "2.0", "id": True, "result": False})
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
            _response(request_id, None)
            continue
        _response(
            request_id,
            result,
            unrelated_numeric_id=scenario == "unrelated-numeric-id",
        )


def _responses(scenario: str) -> list[tuple[int, object]]:
    features: dict[str, object] = {
        "shell": False,
        "web": False,
        "apps": False,
        "plugins": False,
        "multi_agent": False,
    }
    config: dict[str, object] = {
        "features": features,
        "approvalPolicy": "never",
        "sandboxMode": "readOnly",
    }
    mcp_items: list[object] = []
    skills: list[object] = []
    hooks: list[object] = []
    apps: list[object] = []
    if scenario == "mcp-callable":
        mcp_items = [{"name": "synthetic"}]
    elif scenario == "app-callable":
        apps = [{"id": "synthetic"}]
    elif scenario == "skill-enabled":
        skills = [{"name": "synthetic"}]
    elif scenario == "hook-enabled":
        hooks = [{"name": "synthetic"}]
    elif scenario == "plugin-enabled-unknown":
        features["plugins"] = True
    elif scenario == "forbidden-feature-enabled":
        features["shell"] = True
    elif scenario == "config-invalid-bool":
        features["shell"] = 1
    elif scenario == "wrong-count":
        mcp_items = [False]
    mcp_result: object = {"items": mcp_items, "nextCursor": None}
    if scenario == "wrong-count":
        mcp_result = {"items": False, "nextCursor": None}
    if scenario == "pagination-overflow":
        overflow_pages = [
            (item, {"items": [], "nextCursor": "more"}) for item in range(4, 25)
        ]
        return [(2, config), (3, {}), *overflow_pages]
    if scenario == "twentieth-page-null":
        pages: list[tuple[int, object]] = []
        for request_id in range(4, 24):
            cursor = None if request_id == 23 else f"cursor-{request_id}"
            pages.append((request_id, {"items": [], "nextCursor": cursor}))
        return [
            (2, config),
            (3, {}),
            *pages,
            (24, {"items": skills}),
            (25, {"items": hooks}),
            (26, {"items": apps}),
        ]
    return [
        (2, config),
        (3, {}),
        (4, mcp_result),
        (5, {"items": skills}),
        (6, {"items": hooks}),
        (7, {"items": apps}),
    ]


if __name__ == "__main__":
    _run(sys.argv[1])
