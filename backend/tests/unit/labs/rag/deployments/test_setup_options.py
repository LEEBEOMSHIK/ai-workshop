from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Literal
from uuid import UUID

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from ai_workshop.config import Settings, get_settings
from ai_workshop.labs.rag.deployments.api import router
from ai_workshop.labs.rag.deployments.domain import ExecutionLocation, ProviderKind
from ai_workshop.labs.rag.deployments.service import (
    get_deployment_health_service,
    get_deployment_registry_service,
)
from ai_workshop.platform.identity.api import get_current_user
from ai_workshop.platform.identity.domain import User, UserRole
from ai_workshop.shared.db import get_session
from ai_workshop.shared.errors import AppError, register_error_handlers
from tests.unit.labs.rag.deployments.test_domain import create_deployment

SETUP_PATH = "/api/v1/admin/rag/deployment-setup-options"
SYNTHETIC_ENDPOINT = "https://synthetic-provider.example.test/v1"
SYNTHETIC_SECRET = "synthetic-secret-value-never-returned"


def settings() -> Settings:
    return Settings(
        _env_file=None,
        environment="test",
        secret_key=SecretStr("synthetic-session-signing-key-value"),
        provider_endpoint_refs={},
        provider_endpoint_dialects={},
        provider_secret_refs={},
    )


def owner() -> User:
    return User(
        id=UUID("20000000-0000-0000-0000-000000000001"),
        display_name="Synthetic owner",
        email="owner@example.test",
        normalized_email="owner@example.test",
        password_hash="synthetic-unused-hash",
        role=UserRole.OWNER,
        is_active=True,
    )


def application(config: Settings, *, role: UserRole | None = UserRole.OWNER) -> FastAPI:
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router)

    async def current_user() -> User:
        if role is None:
            raise AppError("not_authenticated", "Authentication is required.", 401)
        return replace(owner(), role=role)

    async def configured_settings() -> Settings:
        return config

    async def forbidden_dependency() -> AsyncIterator[None]:
        raise AssertionError("Setup options must not access persistence or provider services.")
        yield  # pragma: no cover

    app.dependency_overrides[get_current_user] = current_user
    app.dependency_overrides[get_settings] = configured_settings
    app.dependency_overrides[get_session] = forbidden_dependency
    app.dependency_overrides[get_deployment_registry_service] = forbidden_dependency
    app.dependency_overrides[get_deployment_health_service] = forbidden_dependency
    return app


async def request_options(app: FastAPI) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        return await client.get(SETUP_PATH)


async def test_owner_reads_named_options_without_resolving_or_exposing_values() -> None:
    config = settings().model_copy(update={
        "provider_endpoint_refs": {
            "z-local": "http://synthetic-local.example.test:11434",
            "a-external": SYNTHETIC_ENDPOINT,
        },
        "provider_endpoint_dialects": {"z-local": "ollama"},
        "provider_secret_refs": {"provider-primary": SecretStr(SYNTHETIC_SECRET)},
    })
    response = await request_options(application(config))

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"endpoints", "secret_references", "environment", "generation_presets"}
    assert payload["endpoints"] == [
        {"reference": "a-external", "dialect": "openai"},
        {"reference": "z-local", "dialect": "ollama"},
    ]
    assert payload["secret_references"] == ["provider-primary"]
    for forbidden in (SYNTHETIC_ENDPOINT, SYNTHETIC_SECRET, "http://", "https://", "**********"):
        assert forbidden not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(("role", "status"), [(UserRole.MEMBER, 403), (None, 401)])
async def test_options_are_not_visible_without_owner_access(
    role: UserRole | None, status: int
) -> None:
    response = await request_options(application(settings(), role=role))

    assert response.status_code == status
    assert "endpoints" not in response.text
    assert "generation_presets" not in response.text


async def test_unconfigured_server_returns_empty_connection_options() -> None:
    response = await request_options(application(settings()))

    assert response.status_code == 200
    assert response.json()["endpoints"] == []
    assert response.json()["secret_references"] == []


@pytest.mark.parametrize(
    ("environment", "expected"),
    [("local", "development"), ("test", "development"), ("production", "production")],
)
async def test_setup_environment_matches_runtime_environment(
    environment: Literal["local", "test", "production"], expected: str
) -> None:
    response = await request_options(application(settings().model_copy(update={
        "environment": environment,
    })))

    assert response.status_code == 200
    assert response.json()["environment"] == expected


@pytest.mark.parametrize("reference", [
    "https://synthetic.example.test", "sk-synthetic", "sess-synthetic", "key-synthetic",
    "token-synthetic", "secret-synthetic", "private text", "", " upper-case", "a-" + "a" * 120,
])
async def test_malformed_or_key_looking_reference_names_are_not_exposed(reference: str) -> None:
    config = settings().model_copy(update={
        "provider_endpoint_refs": {reference: SYNTHETIC_ENDPOINT},
        "provider_secret_refs": {reference: SecretStr(SYNTHETIC_SECRET)},
    })
    response = await request_options(application(config))

    assert response.status_code == 200
    assert response.json()["endpoints"] == []
    assert response.json()["secret_references"] == []


async def test_unprepared_values_and_orphan_dialects_are_not_offered() -> None:
    config = settings().model_copy(update={
        "provider_endpoint_refs": {"empty-endpoint": "  "},
        "provider_endpoint_dialects": {"orphan-endpoint": "ollama"},
        "provider_secret_refs": {"empty-credential": SecretStr("  ")},
    })
    response = await request_options(application(config))

    assert response.status_code == 200
    assert response.json()["endpoints"] == []
    assert response.json()["secret_references"] == []


@pytest.mark.parametrize("provider", [
    ProviderKind.LOCAL_OPENAI_COMPATIBLE, ProviderKind.OPENAI_RESPONSES,
    ProviderKind.ANTHROPIC_MESSAGES,
])
async def test_preset_resolves_as_draft_and_validates_for_its_supported_provider(
    provider: ProviderKind,
) -> None:
    from ai_workshop.labs.rag.generation.openai_compatible import LocalOpenAICompatibleRuntime
    from ai_workshop.labs.rag.generation.openai_responses import OpenAIResponsesRuntime
    from ai_workshop.labs.rag.generation.profile import resolve_generation_profile
    from ai_workshop.labs.rag.generation.prompts import load_prompt
    from ai_workshop.labs.rag.models.domain import (
        EvaluationState,
        ModelDefinition,
        ModelKind,
        Profile,
        ProfileKind,
    )

    response = await request_options(application(settings()))
    assert response.status_code == 200
    presets = [
        item for item in response.json()["generation_presets"]
        if provider in item["supported_providers"]
    ]
    assert len(presets) == 1
    preset = presets[0]
    model = ModelDefinition.create(
        kind=ModelKind.LLM, name="Synthetic LLM", version=1,
        config={"model_identifier": "synthetic-model"},
    )
    external = provider in {ProviderKind.OPENAI_RESPONSES, ProviderKind.ANTHROPIC_MESSAGES}
    deployment = create_deployment(
        model_definition_id=model.id,
        provider=provider,
        location=ExecutionLocation.EXTERNAL if external else ExecutionLocation.LOCAL,
        external_transfer=external,
        secret_ref="provider-primary" if external else None,
        transmitted_data_categories=("question", "bounded_history", "evidence") if external else (),
        data_processing_notice_ref="provider-notice-v1" if external else None,
    )
    profile = Profile.create(
        kind=ProfileKind.GENERATION,
        name=preset["name"],
        version=1,
        config=preset["config"],
        bindings=(),
        deployment_version_id=deployment.id,
    )
    resolved = resolve_generation_profile(profile, deployment, model)

    assert profile.evaluation_state is EvaluationState.DRAFT
    assert profile.is_default is False
    assert profile.config["citation_mode"] == "required"
    assert 0 < resolved.max_output_tokens <= 2048
    assert 0 < resolved.context_policy.max_history_turns <= 6
    assert 0 < resolved.context_policy.max_history_tokens <= 2048
    assert load_prompt(resolved.prompt_ref)
    assert load_prompt(resolved.context_prompt_ref)
    assert load_prompt(resolved.prompt_ref) not in response.text
    assert resolved.orchestration is None
    assert resolved.answer_reasoning_effort is None
    if provider is ProviderKind.ANTHROPIC_MESSAGES:
        from ai_workshop.labs.rag.generation.anthropic_messages import AnthropicMessagesRuntime

        AnthropicMessagesRuntime(
            deployment=deployment, endpoint=SYNTHETIC_ENDPOINT, api_key=SYNTHETIC_SECRET,
        ).validate_profile(resolved)
        assert resolved.response_schema_version == 1
        assert resolved.sampling_mode == "provider_default"
        assert resolved.temperature == 1.0
    elif external:
        runtime = OpenAIResponsesRuntime(
            deployment=deployment, endpoint=SYNTHETIC_ENDPOINT, api_key=SYNTHETIC_SECRET,
        )
        runtime._validate_profile(resolved)
        assert resolved.response_schema_version == 1
    else:
        for dialect in ("openai", "ollama"):
            LocalOpenAICompatibleRuntime(
                deployment=deployment, endpoint="http://127.0.0.1:11434", dialect=dialect,
            ).validate_profile(resolved)
        assert resolved.response_schema_version == 2
        assert resolved.evidence_budget is not None
        assert 0 < resolved.evidence_budget.max_groups <= resolved.evidence_budget.max_units <= 64
        assert 0 < resolved.evidence_budget.max_characters <= 16000


async def test_mutating_returned_preset_cannot_change_later_setup_responses() -> None:
    from ai_workshop.labs.rag.deployments.setup_options import deployment_setup_options

    first = deployment_setup_options(settings())
    first.generation_presets[0].config["citation_mode"] = "disabled"
    second = deployment_setup_options(settings())

    assert all(
        item.config["citation_mode"] == "required"
        for item in second.generation_presets
    )
