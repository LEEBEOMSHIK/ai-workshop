from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

ALLOWED_CODEX_APP_SERVER_VERSIONS = frozenset({"0.151.0"})
_SCHEMA_VERSION: Literal["codex-app-server-isolation-gate-v1"] = (
    "codex-app-server-isolation-gate-v1"
)
_SAFE_ERROR_CODE = "codex_isolation_not_enforced"


@dataclass(frozen=True, slots=True)
class IsolationObservation:
    cli_version: str
    config_read: bool
    requirements_read: bool
    effective_tool_inventory_read: bool
    forbidden_builtin_tool_count: int | None
    shell_enabled: bool | None
    web_enabled: bool | None
    apps_enabled: bool | None
    plugins_enabled: bool | None
    multi_agent_enabled: bool | None
    mcp_callable_count: int | None
    app_callable_count: int | None
    plugin_enabled_count: int | None
    skill_enabled_count: int | None
    hook_enabled_count: int | None
    approval_policy: str | None
    sandbox_mode: str | None


@dataclass(frozen=True, slots=True)
class IsolationViolation:
    rule_id: str


@dataclass(frozen=True, slots=True)
class IsolationGateReport:
    schema_version: Literal["codex-app-server-isolation-gate-v1"]
    status: Literal["pass", "fail"]
    safe_error_code: str | None
    cli_version: str
    violations: tuple[IsolationViolation, ...]
    observation_hash: str


def attest_isolation(observation: IsolationObservation) -> IsolationGateReport:
    violations: list[IsolationViolation] = []

    cli_version = (
        observation.cli_version if type(observation.cli_version) is str else ""
    )

    if cli_version not in ALLOWED_CODEX_APP_SERVER_VERSIONS:
        violations.append(IsolationViolation("cli_version_not_allowed"))
    if not _is_exact_true(observation.config_read):
        violations.append(IsolationViolation("config_state_unverified"))
    if not _is_exact_true(observation.requirements_read):
        violations.append(IsolationViolation("requirements_state_unverified"))
    if not _is_exact_true(observation.effective_tool_inventory_read):
        violations.append(IsolationViolation("tool_inventory_unverified"))

    _append_zero_count_violation(
        violations,
        observation.forbidden_builtin_tool_count,
        "forbidden_builtin_tool",
    )
    _append_disabled_flag_violation(
        violations, observation.shell_enabled, "shell_enabled"
    )
    _append_disabled_flag_violation(violations, observation.web_enabled, "web_enabled")
    _append_disabled_flag_violation(violations, observation.apps_enabled, "apps_enabled")
    _append_disabled_flag_violation(
        violations, observation.plugins_enabled, "plugins_enabled"
    )
    _append_disabled_flag_violation(
        violations, observation.multi_agent_enabled, "multi_agent_enabled"
    )
    _append_zero_count_violation(
        violations, observation.mcp_callable_count, "mcp_callable"
    )
    _append_zero_count_violation(
        violations, observation.app_callable_count, "app_callable"
    )
    _append_zero_count_violation(
        violations, observation.plugin_enabled_count, "plugin_enabled"
    )
    _append_zero_count_violation(
        violations, observation.skill_enabled_count, "skill_enabled"
    )
    _append_zero_count_violation(violations, observation.hook_enabled_count, "hook_enabled")

    if not _is_exact_never_policy(observation.approval_policy):
        violations.append(IsolationViolation("approval_policy_not_never"))
    if not _is_exact_read_only_sandbox(observation.sandbox_mode):
        violations.append(IsolationViolation("sandbox_not_read_only"))

    status: Literal["pass", "fail"] = "pass" if not violations else "fail"
    return IsolationGateReport(
        schema_version=_SCHEMA_VERSION,
        status=status,
        safe_error_code=None if status == "pass" else _SAFE_ERROR_CODE,
        cli_version=cli_version,
        violations=tuple(violations),
        observation_hash=_observation_hash(observation),
    )


def _is_exact_true(value: object) -> bool:
    return type(value) is bool and value is True


def _is_exact_false(value: object) -> bool:
    return type(value) is bool and value is False


def _is_exact_zero_count(value: object) -> bool:
    return type(value) is int and value == 0


def _is_exact_never_policy(value: object) -> bool:
    return type(value) is str and value == "never"


def _is_exact_read_only_sandbox(value: object) -> bool:
    return type(value) is str and value == "readOnly"


def _append_disabled_flag_violation(
    violations: list[IsolationViolation], value: bool | None, rule_id: str
) -> None:
    if not _is_exact_false(value):
        violations.append(IsolationViolation(rule_id))


def _append_zero_count_violation(
    violations: list[IsolationViolation], value: int | None, rule_id: str
) -> None:
    if not _is_exact_zero_count(value):
        violations.append(IsolationViolation(rule_id))


def _observation_hash(observation: IsolationObservation) -> str:
    payload = {
        "app_callable_count": _normalized_count(observation.app_callable_count),
        "app_callable_count_known": _is_exact_count(observation.app_callable_count),
        "apps_enabled": _normalized_flag(observation.apps_enabled),
        "apps_enabled_known": _is_exact_bool(observation.apps_enabled),
        "approval_policy_is_never": _is_exact_never_policy(
            observation.approval_policy
        ),
        "approval_policy_known": type(observation.approval_policy) is str,
        "cli_version": observation.cli_version if type(observation.cli_version) is str else "",
        "config_read": _normalized_flag(observation.config_read),
        "config_read_known": _is_exact_bool(observation.config_read),
        "effective_tool_inventory_read": _normalized_flag(
            observation.effective_tool_inventory_read
        ),
        "effective_tool_inventory_read_known": _is_exact_bool(
            observation.effective_tool_inventory_read
        ),
        "forbidden_builtin_tool_count": _normalized_count(
            observation.forbidden_builtin_tool_count
        ),
        "forbidden_builtin_tool_count_known": _is_exact_count(
            observation.forbidden_builtin_tool_count
        ),
        "hook_enabled_count": _normalized_count(observation.hook_enabled_count),
        "hook_enabled_count_known": _is_exact_count(observation.hook_enabled_count),
        "mcp_callable_count": _normalized_count(observation.mcp_callable_count),
        "mcp_callable_count_known": _is_exact_count(observation.mcp_callable_count),
        "multi_agent_enabled": _normalized_flag(observation.multi_agent_enabled),
        "multi_agent_enabled_known": _is_exact_bool(observation.multi_agent_enabled),
        "plugin_enabled_count": _normalized_count(observation.plugin_enabled_count),
        "plugin_enabled_count_known": _is_exact_count(observation.plugin_enabled_count),
        "plugins_enabled": _normalized_flag(observation.plugins_enabled),
        "plugins_enabled_known": _is_exact_bool(observation.plugins_enabled),
        "requirements_read": _normalized_flag(observation.requirements_read),
        "requirements_read_known": _is_exact_bool(observation.requirements_read),
        "sandbox_is_read_only": _is_exact_read_only_sandbox(observation.sandbox_mode),
        "sandbox_mode_known": type(observation.sandbox_mode) is str,
        "shell_enabled": _normalized_flag(observation.shell_enabled),
        "shell_enabled_known": _is_exact_bool(observation.shell_enabled),
        "skill_enabled_count": _normalized_count(observation.skill_enabled_count),
        "skill_enabled_count_known": _is_exact_count(observation.skill_enabled_count),
        "web_enabled": _normalized_flag(observation.web_enabled),
        "web_enabled_known": _is_exact_bool(observation.web_enabled),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_exact_bool(value: object) -> bool:
    return type(value) is bool


def _is_exact_count(value: object) -> bool:
    return type(value) is int


def _normalized_flag(value: bool | None) -> bool:
    return value is True


def _normalized_count(value: int | None) -> int:
    if type(value) is int:
        return value
    return -1
