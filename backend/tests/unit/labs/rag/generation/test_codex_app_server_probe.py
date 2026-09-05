from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

import ai_workshop.labs.rag.generation.codex_app_server_probe as probe_module
from ai_workshop.labs.rag.generation.codex_app_server_gate import attest_isolation
from ai_workshop.labs.rag.generation.codex_app_server_probe import CodexAppServerProbe

_FAKE_SERVER = (
    Path(__file__).parents[4] / "fixtures" / "codex_app_server" / "fake_app_server.py"
)


def _probe(
    tmp_path: Path,
    scenario: str,
    *,
    timeout_seconds: float = 1.0,
    cli_version: str = "0.151.0",
) -> CodexAppServerProbe:
    return CodexAppServerProbe(
        command=(
            sys.executable,
            str(_FAKE_SERVER),
            scenario,
            "app-server",
            "--stdio",
            "--strict-config",
        ),
        codex_home=tmp_path / "dedicated-codex-home",
        empty_cwd=tmp_path / "empty-cwd",
        timeout_seconds=timeout_seconds,
        cli_version=cli_version,
    )


@pytest.mark.asyncio
async def test_known_surfaces_are_parsed_but_tool_inventory_remains_unverified(
    tmp_path: Path,
) -> None:
    observation = await _probe(tmp_path, "isolated").probe()

    assert observation.cli_version == "0.151.0"
    assert observation.config_read is True
    assert observation.requirements_read is True
    assert observation.effective_tool_inventory_read is False
    assert observation.forbidden_builtin_tool_count is None
    assert observation.shell_enabled is False
    assert observation.web_enabled is False
    assert observation.apps_enabled is False
    assert observation.plugins_enabled is False
    assert observation.multi_agent_enabled is False
    assert observation.mcp_callable_count == 0
    assert observation.app_callable_count == 0
    assert observation.plugin_enabled_count is None
    assert observation.skill_enabled_count == 0
    assert observation.hook_enabled_count == 0
    assert observation.approval_policy == "never"
    assert observation.sandbox_mode == "readOnly"

    rule_ids = {violation.rule_id for violation in attest_isolation(observation).violations}
    assert {"tool_inventory_unverified", "forbidden_builtin_tool", "plugin_enabled"} <= rule_ids


@pytest.mark.asyncio
async def test_cli_version_comes_from_the_pre_spawn_caller_value(
    tmp_path: Path,
) -> None:
    observation = await _probe(
        tmp_path, "isolated", cli_version="caller-supplied-version"
    ).probe()

    assert observation.cli_version == "caller-supplied-version"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "field", "expected"),
    [
        ("mcp-callable", "mcp_callable_count", 1),
        ("app-callable", "app_callable_count", 1),
        ("skill-enabled", "skill_enabled_count", 1),
        ("hook-enabled", "hook_enabled_count", 1),
        ("plugin-enabled-unknown", "plugins_enabled", True),
        ("forbidden-feature-enabled", "shell_enabled", True),
    ],
)
async def test_probe_reports_known_non_isolated_surfaces(
    tmp_path: Path, scenario: str, field: str, expected: object
) -> None:
    observation = await _probe(tmp_path, scenario).probe()

    assert getattr(observation, field) == expected
    assert observation.effective_tool_inventory_read is False
    assert observation.forbidden_builtin_tool_count is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "timeout_seconds"),
    [
        ("rpc-error", 1.0),
        ("invalid-json", 1.0),
        ("stderr-secret", 1.0),
        ("oversize-line", 1.0),
        ("pagination-overflow", 1.0),
        ("timeout", 0.05),
        ("malformed-envelope", 1.0),
        ("requirements-null", 1.0),
        ("config-invalid-bool", 1.0),
        ("wrong-count", 1.0),
        ("initialize-version-only", 1.0),
        ("initialize-wrong-home", 1.0),
        ("initialize-invalid-codex-home", 1.0),
        ("initialize-invalid-platform-family", 1.0),
        ("initialize-invalid-platform-os", 1.0),
        ("initialize-invalid-user-agent", 1.0),
        ("config-missing-shell-tool", 1.0),
        ("config-missing-web-search", 1.0),
        ("config-missing-apps", 1.0),
        ("config-missing-plugins", 1.0),
        ("config-missing-multi-agent", 1.0),
        ("mcp-missing-auth-status", 1.0),
        ("mcp-invalid-auth-status", 1.0),
        ("mcp-invalid-name", 1.0),
        ("mcp-invalid-resource-templates", 1.0),
        ("mcp-invalid-resources", 1.0),
        ("mcp-invalid-tools", 1.0),
        ("mcp-tool-missing-input-schema", 1.0),
        ("mcp-tool-invalid-name", 1.0),
        ("mcp-invalid-cursor", 1.0),
        ("skills-missing-cwd", 1.0),
        ("skills-wrong-cwd", 1.0),
        ("skills-duplicate-cwd", 1.0),
        ("skills-discovery-error", 1.0),
        ("skills-missing-container", 1.0),
        ("skill-malformed-metadata", 1.0),
        ("hooks-missing-cwd", 1.0),
        ("hooks-wrong-cwd", 1.0),
        ("hooks-duplicate-cwd", 1.0),
        ("hooks-discovery-error", 1.0),
        ("hooks-missing-container", 1.0),
        ("hook-malformed-metadata", 1.0),
        ("app-missing-id", 1.0),
        ("app-invalid-id", 1.0),
        ("app-invalid-enabled", 1.0),
        ("app-invalid-callable", 1.0),
        ("app-invalid-runtime-name", 1.0),
        ("app-callable-disabled", 1.0),
    ],
)
async def test_protocol_failures_fail_closed_without_transcript_exposure(
    tmp_path: Path, scenario: str, timeout_seconds: float
) -> None:
    observation = await _probe(tmp_path, scenario, timeout_seconds=timeout_seconds).probe()

    assert observation.cli_version == "0.151.0"
    assert observation.config_read is False
    assert observation.requirements_read is False
    assert observation.effective_tool_inventory_read is False
    assert observation.forbidden_builtin_tool_count is None
    assert observation.shell_enabled is None
    assert observation.web_enabled is None
    assert observation.apps_enabled is None
    assert observation.plugins_enabled is None
    assert observation.multi_agent_enabled is None
    assert observation.mcp_callable_count is None
    assert observation.app_callable_count is None
    assert observation.plugin_enabled_count is None
    assert observation.skill_enabled_count is None
    assert observation.hook_enabled_count is None
    assert observation.approval_policy is None
    assert observation.sandbox_mode is None


@pytest.mark.asyncio
async def test_non_read_only_sandbox_is_not_exposed_as_raw_config(
    tmp_path: Path,
) -> None:
    observation = await _probe(tmp_path, "unsafe-sandbox").probe()

    assert observation.config_read is True
    assert observation.sandbox_mode is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("scenario", "field"),
    [
        ("skill-disabled", "skill_enabled_count"),
        ("hook-disabled", "hook_enabled_count"),
    ],
)
async def test_disabled_discovery_items_are_not_counted(
    tmp_path: Path, scenario: str, field: str
) -> None:
    observation = await _probe(tmp_path, scenario).probe()

    assert getattr(observation, field) == 0


@pytest.mark.asyncio
async def test_stderr_backpressure_is_continuously_drained(tmp_path: Path) -> None:
    observation = await asyncio.wait_for(
        _probe(tmp_path, "stderr-backpressure", timeout_seconds=1.0).probe(), timeout=1.5
    )

    assert observation.config_read is True
    assert observation.requirements_read is True


@pytest.mark.asyncio
async def test_descendant_held_pipe_cleanup_is_bounded_and_fails_closed(
    tmp_path: Path,
) -> None:
    observation = await asyncio.wait_for(
        _probe(tmp_path, "descendant-held-pipe", timeout_seconds=0.05).probe(), timeout=0.8
    )

    assert observation.config_read is False
    assert observation.mcp_callable_count is None


@pytest.mark.asyncio
async def test_unrelated_numeric_response_ids_are_ignored(tmp_path: Path) -> None:
    observation = await _probe(tmp_path, "unrelated-numeric-id").probe()

    assert observation.config_read is True
    assert observation.requirements_read is True
    assert observation.mcp_callable_count == 0


@pytest.mark.asyncio
async def test_schema_permitted_jsonrpc_response_header_is_tolerated(tmp_path: Path) -> None:
    observation = await _probe(tmp_path, "unexpected-jsonrpc-header").probe()

    assert observation.config_read is True
    assert observation.requirements_read is True


@pytest.mark.asyncio
async def test_wrong_typed_response_id_is_not_accepted_as_the_matching_response(
    tmp_path: Path,
) -> None:
    observation = await _probe(tmp_path, "wrong-id-type").probe()

    assert observation.config_read is True
    assert observation.requirements_read is True


@pytest.mark.asyncio
async def test_twentieth_mcp_page_with_null_cursor_is_accepted(tmp_path: Path) -> None:
    observation = await _probe(tmp_path, "twentieth-page-null").probe()

    assert observation.config_read is True
    assert observation.requirements_read is True
    assert observation.mcp_callable_count == 0


@pytest.mark.asyncio
async def test_missing_terminal_mcp_cursor_is_accepted(tmp_path: Path) -> None:
    observation = await _probe(tmp_path, "mcp-missing-terminal-cursor").probe()

    assert observation.config_read is True
    assert observation.requirements_read is True
    assert observation.mcp_callable_count == 0


@pytest.mark.asyncio
async def test_cleanup_race_returns_a_fail_closed_observation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    original_cleanup = probe_module._cleanup_process

    async def cleanup_race(*args: object) -> bool:
        await original_cleanup(*args)  # type: ignore[arg-type]
        raise ProcessLookupError

    monkeypatch.setattr(probe_module, "_cleanup_process", cleanup_race)

    observation = await _probe(tmp_path, "isolated").probe()

    assert observation.config_read is False
    assert observation.mcp_callable_count is None


@pytest.mark.asyncio
async def test_cleanup_kills_and_reaps_a_terminate_resistant_process() -> None:
    class TerminateResistantProcess:
        def __init__(self) -> None:
            self.events: list[str] = []
            self.returncode: int | None = None
            self.stdout = None

        def terminate(self) -> None:
            self.events.append("terminate")

        def kill(self) -> None:
            self.events.append("kill")
            self.returncode = -9

        async def wait(self) -> int:
            self.events.append("wait")
            if self.returncode is None:
                await asyncio.Future[int]()
            return self.returncode

    process = TerminateResistantProcess()

    await asyncio.wait_for(probe_module._cleanup_process(process, None), timeout=0.8)

    assert process.events == ["terminate", "wait", "kill", "wait"]
    assert process.returncode == -9


@pytest.mark.asyncio
async def test_stalled_windows_worker_dispatch_fails_closed_within_its_deadline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def stalled_to_thread(*args: object, **kwargs: object) -> object:
        await asyncio.Future[object]()

    monkeypatch.setattr(probe_module.asyncio, "to_thread", stalled_to_thread)

    observation = await asyncio.wait_for(
        _probe(tmp_path, "isolated", timeout_seconds=0.05).probe(), timeout=0.9
    )

    assert observation.config_read is False
    assert observation.mcp_callable_count is None


@pytest.mark.asyncio
async def test_unsupported_subprocess_loop_fails_closed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    async def unavailable_subprocess(*args: object, **kwargs: object) -> object:
        raise NotImplementedError

    monkeypatch.setattr(probe_module.sys, "platform", "linux")
    monkeypatch.setattr(
        probe_module.asyncio, "create_subprocess_exec", unavailable_subprocess
    )

    observation = await _probe(tmp_path, "isolated").probe()

    assert observation.config_read is False
    assert observation.mcp_callable_count is None


def test_minimal_environment_preserves_only_windows_launch_essentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SystemRoot", r"C:\Windows")
    monkeypatch.setenv("ComSpec", r"C:\Windows\System32\cmd.exe")
    monkeypatch.setenv("PATHEXT", ".COM;.EXE")
    monkeypatch.setenv("PATH", r"C:\Windows\System32")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setenv("CODEX_HOME", r"C:\Users\owner\.codex")

    environment = CodexAppServerProbe.build_minimal_environment(Path(r"C:\\isolated"))

    assert environment == {
        "CODEX_HOME": r"C:\isolated",
        "ComSpec": r"C:\Windows\System32\cmd.exe",
        "PATHEXT": ".COM;.EXE",
        "PATH": r"C:\Windows\System32",
        "SystemRoot": r"C:\Windows",
    }
