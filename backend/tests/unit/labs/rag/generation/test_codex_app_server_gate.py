from dataclasses import replace

import pytest

from ai_workshop.labs.rag.generation.codex_app_server_gate import (
    ALLOWED_CODEX_APP_SERVER_VERSIONS,
    IsolationObservation,
    attest_isolation,
)


def safe_observation() -> IsolationObservation:
    return IsolationObservation(
        cli_version="0.151.0",
        config_read=True,
        requirements_read=True,
        effective_tool_inventory_read=True,
        forbidden_builtin_tool_count=0,
        shell_enabled=False,
        web_enabled=False,
        apps_enabled=False,
        plugins_enabled=False,
        multi_agent_enabled=False,
        mcp_callable_count=0,
        app_callable_count=0,
        plugin_enabled_count=0,
        skill_enabled_count=0,
        hook_enabled_count=0,
        approval_policy="never",
        sandbox_mode="readOnly",
    )


def test_allowed_version_is_pinned() -> None:
    assert frozenset({"0.151.0"}) == ALLOWED_CODEX_APP_SERVER_VERSIONS


def test_attestation_passes_only_when_every_inventory_is_proven_empty() -> None:
    report = attest_isolation(safe_observation())

    assert report.schema_version == "codex-app-server-isolation-gate-v1"
    assert report.status == "pass"
    assert report.safe_error_code is None
    assert report.violations == ()
    assert report.cli_version == "0.151.0"


@pytest.mark.parametrize(
    ("change", "rule_id"),
    [
        ({"cli_version": "0.152.0"}, "cli_version_not_allowed"),
        ({"config_read": False}, "config_state_unverified"),
        ({"requirements_read": False}, "requirements_state_unverified"),
        ({"effective_tool_inventory_read": False}, "tool_inventory_unverified"),
        ({"forbidden_builtin_tool_count": 1}, "forbidden_builtin_tool"),
        ({"forbidden_builtin_tool_count": None}, "forbidden_builtin_tool"),
        ({"shell_enabled": True}, "shell_enabled"),
        ({"shell_enabled": None}, "shell_enabled"),
        ({"web_enabled": True}, "web_enabled"),
        ({"web_enabled": None}, "web_enabled"),
        ({"apps_enabled": True}, "apps_enabled"),
        ({"apps_enabled": None}, "apps_enabled"),
        ({"plugins_enabled": True}, "plugins_enabled"),
        ({"plugins_enabled": None}, "plugins_enabled"),
        ({"multi_agent_enabled": True}, "multi_agent_enabled"),
        ({"multi_agent_enabled": None}, "multi_agent_enabled"),
        ({"mcp_callable_count": 1}, "mcp_callable"),
        ({"mcp_callable_count": None}, "mcp_callable"),
        ({"app_callable_count": 1}, "app_callable"),
        ({"app_callable_count": None}, "app_callable"),
        ({"plugin_enabled_count": 1}, "plugin_enabled"),
        ({"plugin_enabled_count": None}, "plugin_enabled"),
        ({"skill_enabled_count": 1}, "skill_enabled"),
        ({"skill_enabled_count": None}, "skill_enabled"),
        ({"hook_enabled_count": 1}, "hook_enabled"),
        ({"hook_enabled_count": None}, "hook_enabled"),
        ({"approval_policy": "ask"}, "approval_policy_not_never"),
        ({"approval_policy": None}, "approval_policy_not_never"),
        ({"sandbox_mode": "workspaceWrite"}, "sandbox_not_read_only"),
        ({"sandbox_mode": None}, "sandbox_not_read_only"),
    ],
)
def test_attestation_fails_closed_for_each_forbidden_state(
    change: dict[str, object], rule_id: str
) -> None:
    report = attest_isolation(replace(safe_observation(), **change))

    assert report.status == "fail"
    assert report.safe_error_code == "codex_isolation_not_enforced"
    assert rule_id in {item.rule_id for item in report.violations}


@pytest.mark.parametrize(
    ("change", "rule_id"),
    [
        ({"config_read": 1}, "config_state_unverified"),
        ({"forbidden_builtin_tool_count": False}, "forbidden_builtin_tool"),
    ],
)
def test_attestation_rejects_malformed_decoded_types(
    change: dict[str, object], rule_id: str
) -> None:
    report = attest_isolation(replace(safe_observation(), **change))

    assert report.status == "fail"
    assert report.safe_error_code == "codex_isolation_not_enforced"
    assert rule_id in {item.rule_id for item in report.violations}


def test_canonical_hash_is_deterministic_for_safe_observations() -> None:
    safe_report = attest_isolation(safe_observation())
    repeated_report = attest_isolation(safe_observation())

    assert safe_report.observation_hash == repeated_report.observation_hash


def test_canonical_hash_distinguishes_safe_and_unknown_optional_states() -> None:
    safe_report = attest_isolation(safe_observation())
    unknown_count_report = attest_isolation(
        replace(safe_observation(), mcp_callable_count=None)
    )
    unknown_flag_report = attest_isolation(
        replace(safe_observation(), shell_enabled=None)
    )

    assert safe_report.observation_hash != unknown_count_report.observation_hash
    assert safe_report.observation_hash != unknown_flag_report.observation_hash


def test_canonical_hash_changes_for_policy_and_sandbox_states() -> None:
    safe_report = attest_isolation(safe_observation())
    approval_report = attest_isolation(
        replace(safe_observation(), approval_policy="ask")
    )
    sandbox_report = attest_isolation(
        replace(safe_observation(), sandbox_mode="workspaceWrite")
    )

    assert safe_report.observation_hash != approval_report.observation_hash
    assert safe_report.observation_hash != sandbox_report.observation_hash
