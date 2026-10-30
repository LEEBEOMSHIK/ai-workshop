from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from ai_workshop.config import Settings
from ai_workshop.labs.rag.configurations.domain import ExternalTransferApprovalConfirmation
from ai_workshop.labs.rag.deployments.domain import DeploymentValidationError, ProviderKind
from ai_workshop.labs.rag.deployments.schemas import DeploymentVersionCreate
from ai_workshop.labs.rag.deployments.service import DeploymentRegistryService
from ai_workshop.labs.rag.generation.domain import generation_disclosure
from ai_workshop.labs.rag.generation.runtime_resolver import builtin_generation_runtime_factories
from ai_workshop.labs.rag.models.domain import Profile, ProfileKind
from ai_workshop.labs.rag.models.service import RagModelRegistryService
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.deployments.test_domain import create_deployment
from tests.unit.labs.rag.models.test_profiles import generation_config


def native_deployment():
    assert "anthropic_messages" in ProviderKind._value2member_map_
    return create_deployment(provider=ProviderKind("anthropic_messages"))


def native_config():
    config = generation_config()
    config["generation"] = {
        **config["generation"],
        "sampling_mode": "provider_default",
        "temperature": 1.0,
    }
    return config


def test_native_disclosure_does_not_reuse_openai_approval():
    disclosure = generation_disclosure(native_deployment())
    assert disclosure.version == "anthropic-generation-v1"
    assert "Anthropic" in disclosure.text
    assert "OpenAI" not in disclosure.text
    ExternalTransferApprovalConfirmation(True, disclosure.version)


@pytest.mark.parametrize("change", [{"secret_ref": None}, {"external_transfer": False}])
def test_native_deployment_requires_external_secret_contract(change):
    selected = native_deployment()
    with pytest.raises(DeploymentValidationError):
        replace(selected, **change)


def test_typed_anthropic_endpoint_is_explicit():
    value = Settings(
        _env_file=None,
        secret_key=SecretStr("synthetic-settings-signing-key-value"),
        provider_endpoint_refs={"native-provider": "https://provider.example.test/v1"},
        provider_endpoint_dialects={"native-provider": "anthropic"},
    )
    assert value.provider_endpoint_dialects["native-provider"] == "anthropic"


@pytest.mark.parametrize(
    ("provider", "dialect"),
    [
        ("anthropic_messages", "openai"),
        ("anthropic_messages", "ollama"),
        ("openai_responses", "anthropic"),
        ("local_openai_compatible", "anthropic"),
    ],
)
def test_runtime_and_registry_reject_cross_provider_endpoint(provider, dialect):
    selected = native_deployment()
    if provider != "anthropic_messages":
        from ai_workshop.labs.rag.deployments.domain import ExecutionLocation

        local = provider == "local_openai_compatible"
        selected = replace(
            selected,
            provider=ProviderKind(provider),
            location=ExecutionLocation.LOCAL if local else selected.location,
            external_transfer=not local,
            transmitted_data_categories=() if local else ("question",),
            data_processing_notice_ref=None if local else "notice-version",
        )
    factories = builtin_generation_runtime_factories(
        provider_endpoint_dialects={selected.endpoint_ref: dialect}
    )
    with pytest.raises(ValueError):
        factories[selected.provider](selected, "https://provider.example.test/v1", "synthetic")
    registry = DeploymentRegistryService(
        object(),
        endpoint_refs={selected.endpoint_ref: "url"},
        secret_refs={selected.secret_ref: SecretStr("synthetic")},
        endpoint_dialects={selected.endpoint_ref: dialect},
    )
    request = DeploymentVersionCreate.model_validate(
        {key: getattr(selected, key) for key in DeploymentVersionCreate.model_fields}
    )
    with pytest.raises(AppError, match="dialect"):
        registry._validate_references(request)


@pytest.mark.parametrize(
    "generation_change",
    [
        {"sampling_mode": "explicit"},
        {"sampling_mode": "unknown"},
        {"temperature": 0.0},
        {"response_schema_version": 2},
        {"top_p": 1.0},
    ],
)
async def test_profile_registration_rejects_incompatible_native_settings(generation_change):
    selected = native_deployment()
    config = native_config()
    config["generation"].update(generation_change)
    repo = SimpleNamespace(
        profile_version_exists=AsyncMock(return_value=False),
        find_models=AsyncMock(side_effect=[[], [SimpleNamespace(kind="llm")]]),
        find_deployment_version=AsyncMock(return_value=selected),
        add_profile=AsyncMock(),
    )
    from ai_workshop.labs.rag.models.domain import ModelKind

    repo.find_models.side_effect = [[], [SimpleNamespace(kind=ModelKind.LLM)]]
    with pytest.raises(AppError):
        await RagModelRegistryService(repo).register_profile(
            kind=ProfileKind.GENERATION,
            name="Synthetic profile",
            version=1,
            config=config,
            bindings=(),
            deployment_version_id=selected.id,
        )
    repo.add_profile.assert_not_awaited()


def test_unknown_sampling_mode_is_not_silently_ignored():
    config = generation_config()
    config["generation"]["sampling_mode"] = "unknown"
    with pytest.raises(ValueError):
        Profile.create(
            kind=ProfileKind.GENERATION,
            name="Synthetic",
            version=1,
            config=config,
            bindings=(),
            deployment_version_id=create_deployment().id,
        )


@pytest.mark.parametrize(
    "provider", [ProviderKind.OPENAI_RESPONSES, ProviderKind.LOCAL_OPENAI_COMPATIBLE]
)
def test_provider_default_cannot_be_attached_to_existing_provider(provider):
    from ai_workshop.labs.rag.deployments.domain import ExecutionLocation
    from ai_workshop.labs.rag.models.provider_policy import validate_provider_profile_config
    from tests.unit.labs.rag.generation.test_openai_responses import profile

    local = provider is ProviderKind.LOCAL_OPENAI_COMPATIBLE
    selected = create_deployment(
        provider=provider,
        location=ExecutionLocation.LOCAL if local else ExecutionLocation.EXTERNAL,
        external_transfer=not local,
        secret_ref=None if local else "provider-primary",
        transmitted_data_categories=() if local else ("question",),
        data_processing_notice_ref=None if local else "provider-notice",
    )
    with pytest.raises(ValueError, match="only supported"):
        validate_provider_profile_config(native_config(), selected)
    with pytest.raises(ValueError, match="only supported"):
        replace(profile(), deployment=selected, sampling_mode="provider_default")


async def test_native_profile_registration_keeps_draft_and_existing_defaults():
    from ai_workshop.labs.rag.models.domain import EvaluationState, ModelKind

    selected = native_deployment()
    repo = SimpleNamespace(
        profile_version_exists=AsyncMock(return_value=False),
        find_models=AsyncMock(side_effect=[[], [SimpleNamespace(kind=ModelKind.LLM)]]),
        find_deployment_version=AsyncMock(return_value=selected),
        add_profile=AsyncMock(side_effect=lambda profile: profile),
    )
    created = await RagModelRegistryService(repo).register_profile(
        kind=ProfileKind.GENERATION,
        name="Synthetic Claude candidate",
        version=1,
        config=native_config(),
        bindings=(),
        deployment_version_id=selected.id,
    )
    assert created.evaluation_state is EvaluationState.DRAFT
    assert not created.is_default
    repo.add_profile.assert_awaited_once_with(created)


@pytest.mark.parametrize(
    ("change", "dialect", "observed", "expected"),
    [
        ({}, "anthropic", "exact", True),
        ({}, "openai", "exact", False),
        ({}, "anthropic", "different", False),
        ({"sampling_mode": "explicit"}, "anthropic", "exact", False),
        ({"temperature": 0.0}, "anthropic", "exact", False),
        ({"response_schema_version": 2}, "anthropic", "exact", False),
        ({"top_p": 1.0}, "anthropic", "exact", False),
    ],
)
async def test_native_readiness_needs_exact_health_and_compatible_profile(
    change,
    dialect,
    observed,
    expected,
):
    from ai_workshop.labs.rag.generation.readiness import SqlAlchemyGenerationReadiness

    selected = native_deployment()
    config = native_config()
    config["generation"].update(change)
    service = object.__new__(SqlAlchemyGenerationReadiness)
    service.settings = SimpleNamespace(
        environment="production", provider_endpoint_dialects={selected.endpoint_ref: dialect}
    )
    service.profiles = SimpleNamespace(
        find_profile=AsyncMock(
            return_value=SimpleNamespace(
                bindings=(), deployment_version_id=selected.id, config=config
            )
        )
    )
    service.deployments = SimpleNamespace(
        get_version=AsyncMock(return_value=selected),
        latest_health_check=AsyncMock(
            return_value=SimpleNamespace(
                status="ready",
                safe_error_code=None,
                observed_provider_model_id=(
                    selected.provider_model_id if observed == "exact" else "different-model"
                ),
            )
        ),
    )
    assert await service.is_ready(selected.id) is expected
