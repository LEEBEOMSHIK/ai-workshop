from dataclasses import asdict
from os import environ
from pathlib import Path
from subprocess import run
from sys import executable

import pytest

from ai_workshop.config import Settings
from tools.e2e_runtime import (
    E2ERuntimeContractError,
    build_reset_scope,
    validate_prepared_e2e,
)
from tools.reset_e2e_state import reset_e2e_state

PROJECT = "ai-workshop-smoke-task14-runtime-0901"
SAFE_ENVIRONMENT = {
    "AI_WORKSHOP_E2E_PREPARED": "1",
    "AI_WORKSHOP_E2E_RESET": "1",
    "AI_WORKSHOP_E2E_PROJECT": PROJECT,
}


def test_reset_cli_module_entrypoint_reaches_safe_contract_check() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    result = run(
        [executable, "-m", "tools.reset_e2e_state"],
        cwd=backend_root,
        env={
            **environ,
            "PYTHONPATH": str(backend_root / "src"),
            "AI_WORKSHOP_ENVIRONMENT": "local",
            "AI_WORKSHOP_SECRET_KEY": "x" * 32,
            "AI_WORKSHOP_E2E_PREPARED": "0",
            "AI_WORKSHOP_E2E_RESET": "0",
            "AI_WORKSHOP_E2E_PROJECT": "",
        },
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 2
    assert "scripts/smoke.ps1" in result.stdout
    assert "Traceback" not in result.stderr


def test_unprepared_actual_elasticsearch_test_fails_before_client_attempt() -> None:
    backend_root = Path(__file__).resolve().parents[2]
    result = run(
        [
            executable,
            "-m",
            "pytest",
            "-p",
            "no:cacheprovider",
            (
                "tests/e2e/test_rag_search_flow.py::"
                "test_ready_documents_remain_searchable_after_another_projection_activates"
            ),
            "-q",
        ],
        cwd=backend_root,
        env={
            **environ,
            "PYTHONPATH": str(backend_root / "src"),
            "AI_WORKSHOP_ENVIRONMENT": "test",
            "AI_WORKSHOP_SECRET_KEY": "x" * 32,
            "AI_WORKSHOP_E2E": "1",
            "AI_WORKSHOP_E2E_PREPARED": "0",
            "AI_WORKSHOP_E2E_RESET": "0",
            "AI_WORKSHOP_E2E_PROJECT": PROJECT,
            "AI_WORKSHOP_E2E_BASE_URL": "http://127.0.0.1:1",
            "AI_WORKSHOP_ELASTICSEARCH_URL": "http://127.0.0.1:1",
            "AI_WORKSHOP_ELASTICSEARCH_INDEX_PREFIX": f"{PROJECT}-rag",
        },
        capture_output=True,
        check=False,
        text=True,
    )
    output = result.stdout + result.stderr

    assert result.returncode == 1
    assert "Prepared E2E state is required; run scripts/smoke.ps1." in output
    assert "ConnectionError" not in output
    assert "Connection refused" not in output


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "test",
        "secret_key": "x" * 32,
        "database_url": (
            "postgresql+psycopg://ai_workshop:ai_workshop@postgres:5432/ai_workshop"
        ),
        "redis_url": "redis://redis:6379/0",
        "elasticsearch_url": "http://elasticsearch:9200",
        "elasticsearch_index_prefix": f"{PROJECT}-rag",
    }
    values.update(overrides)
    return Settings(**values)


def test_prepared_e2e_requires_test_environment_and_explicit_opt_in() -> None:
    validate_prepared_e2e(_settings(), SAFE_ENVIRONMENT)

    for settings, environment in (
        (_settings(environment="local"), SAFE_ENVIRONMENT),
        (_settings(), {**SAFE_ENVIRONMENT, "AI_WORKSHOP_E2E_PREPARED": "0"}),
    ):
        with pytest.raises(E2ERuntimeContractError, match="scripts/smoke.ps1"):
            validate_prepared_e2e(settings, environment)


@pytest.mark.parametrize(
    ("settings_overrides", "environment_overrides"),
    (
        ({"environment": "local"}, {}),
        ({}, {"AI_WORKSHOP_E2E_PREPARED": "0"}),
        ({}, {"AI_WORKSHOP_E2E_RESET": "0"}),
        ({}, {"AI_WORKSHOP_E2E_PROJECT": "ai-workshop"}),
        (
            {
                "database_url": (
                    "postgresql+psycopg://ai_workshop:ai_workshop@localhost:5432/"
                    "ai_workshop"
                )
            },
            {},
        ),
        (
            {
                "database_url": (
                    "postgresql+psycopg://ai_workshop:ai_workshop@postgres:5432/other"
                )
            },
            {},
        ),
        ({"redis_url": "redis://localhost:6379/0"}, {}),
        ({"redis_url": "redis://redis:6379/1"}, {}),
        ({"elasticsearch_url": "http://localhost:9200"}, {}),
        ({"elasticsearch_index_prefix": "unscoped-rag"}, {}),
    ),
)
def test_reset_scope_rejects_every_unsafe_target(
    settings_overrides: dict[str, object],
    environment_overrides: dict[str, str],
) -> None:
    environment = {**SAFE_ENVIRONMENT, **environment_overrides}

    with pytest.raises(E2ERuntimeContractError, match="scripts/smoke.ps1"):
        build_reset_scope(_settings(**settings_overrides), environment)


def test_reset_scope_names_only_the_isolated_database_redis_and_exact_es_prefix() -> None:
    scope = build_reset_scope(_settings(), SAFE_ENVIRONMENT)

    assert asdict(scope) == {
        "project_name": PROJECT,
        "database_tables": (
            "rag_profile_model_bindings",
            "rag_profiles",
            "rag_model_definitions",
            "jobs",
            "asset_versions",
            "documents",
            "folders",
            "workspace_memberships",
            "workspaces",
            "users",
        ),
        "redis_database": 0,
        "elasticsearch_index_pattern": f"{PROJECT}-rag-*",
    }


def test_reset_contract_exposes_no_volume_or_model_cache_target() -> None:
    serialized = repr(asdict(build_reset_scope(_settings(), SAFE_ENVIRONMENT))).lower()

    assert "volume" not in serialized
    assert "model-cache" not in serialized
    assert "/models" not in serialized


@pytest.mark.asyncio
async def test_reset_executes_database_redis_and_exact_es_cleanup_in_order() -> None:
    calls: list[tuple[str, object]] = []

    async def wait_for_targets(_settings: Settings) -> None:
        calls.append(("ready", None))

    async def reset_database(_settings: Settings, tables: tuple[str, ...]) -> None:
        calls.append(("database", tables))

    async def reset_redis(_settings: Settings, database: int) -> None:
        calls.append(("redis", database))

    async def reset_elasticsearch(_settings: Settings, pattern: str) -> None:
        calls.append(("elasticsearch", pattern))

    await reset_e2e_state(
        _settings(),
        SAFE_ENVIRONMENT,
        readiness_check=wait_for_targets,
        database_reset=reset_database,
        redis_reset=reset_redis,
        elasticsearch_reset=reset_elasticsearch,
    )

    assert calls == [
        ("ready", None),
        (
            "database",
            (
                "rag_profile_model_bindings",
                "rag_profiles",
                "rag_model_definitions",
                "jobs",
                "asset_versions",
                "documents",
                "folders",
                "workspace_memberships",
                "workspaces",
                "users",
            ),
        ),
        ("redis", 0),
        ("elasticsearch", f"{PROJECT}-rag-*"),
    ]
