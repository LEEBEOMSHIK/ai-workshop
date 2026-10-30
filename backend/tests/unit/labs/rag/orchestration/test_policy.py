from dataclasses import replace

import pytest

from ai_workshop.labs.rag.deployments.domain import ExecutionLocation, ProviderKind
from ai_workshop.labs.rag.generation.profile import resolve_generation_profile
from ai_workshop.labs.rag.models.domain import Profile, ProfileKind, ProfileValidationError
from ai_workshop.labs.rag.models.orchestration_policy import (
    OrchestrationPolicy,
    resolve_orchestration_policy,
)
from tests.unit.labs.rag.generation.test_openai_compatible import profile
from tests.unit.labs.rag.generation.test_profile_resolution import deployment as external_deployment
from tests.unit.labs.rag.generation.test_profile_resolution import generation_profile, llm_model


def configuration(**changes):
    return {
        "engine": "openai_agents",
        "version": 1,
        "max_model_calls": 2,
        "max_tool_calls": 1,
        "max_total_output_tokens": 600,
        **changes,
    }


def test_profile_without_orchestration_preserves_single_generation():
    assert resolve_orchestration_policy({}) is None
    assert profile().orchestration is None


def test_explicit_policy_preserves_exact_limits():
    selected = resolve_orchestration_policy({"orchestration": configuration()})
    assert selected == OrchestrationPolicy(**configuration())
    original = profile()
    resolved = replace(original, response_schema_version=2, orchestration=selected)
    assert resolved.orchestration.max_model_calls == 2
    assert resolved.deployment == original.deployment


@pytest.mark.parametrize("value", [
    None, False, [], {}, configuration(engine="other"), configuration(version=True),
    configuration(max_model_calls=True), configuration(max_model_calls=4),
    configuration(max_tool_calls=2), configuration(max_total_output_tokens=0),
    configuration(retries=1), configuration(manager_model="unregistered-model"),
])
def test_invalid_or_ambiguous_policy_is_rejected(value):
    with pytest.raises(ValueError):
        resolve_orchestration_policy({"orchestration": value})


def test_orchestration_requires_schema_two_and_zero_deployment_retries():
    selected = OrchestrationPolicy(**configuration())
    with pytest.raises(ValueError, match="orchestration"):
        replace(profile(), orchestration=selected)
    with pytest.raises(ValueError, match="orchestration"):
        replace(profile(), response_schema_version=2, orchestration=selected,
                deployment=replace(profile().deployment, max_retries=1))


@pytest.mark.parametrize("provider,location", [
    (ProviderKind.LOCAL_OPENAI_COMPATIBLE, ExecutionLocation.ON_PREMISE),
    (ProviderKind.OPENAI_RESPONSES, ExecutionLocation.EXTERNAL),
])
def test_orchestration_rejects_other_deployment_paths(provider, location):
    selected = OrchestrationPolicy(**configuration())
    exact = (external_deployment() if provider is ProviderKind.OPENAI_RESPONSES
             else replace(profile().deployment, location=location))
    with pytest.raises(ValueError, match="orchestration"):
        replace(profile(), response_schema_version=2, orchestration=selected,
                deployment=exact)


@pytest.mark.parametrize("schema", [1, 2])
def test_registered_generation_profile_resolves_versioned_opt_in(schema):
    exact = replace(external_deployment(), provider=ProviderKind.LOCAL_OPENAI_COMPATIBLE,
                    location=ExecutionLocation.LOCAL, external_transfer=False,
                    transmitted_data_categories=(), data_processing_notice_ref=None,
                    secret_ref=None, max_retries=0)
    config = dict(generation_profile().config)
    config["generation"] = dict(config["generation"], response_schema_version=schema)
    config["orchestration"] = configuration(max_model_calls=3, max_total_output_tokens=1536)

    def create():
        return Profile.create(kind=ProfileKind.GENERATION, name="synthetic-sdk", version=1,
                              config=config, bindings=(), deployment_version_id=exact.id)

    if schema != 2:
        with pytest.raises(ProfileValidationError, match="schema2"):
            create()
        return
    selected = create()
    resolved = resolve_generation_profile(selected, exact, llm_model())
    assert resolved.orchestration == OrchestrationPolicy(**config["orchestration"])
    assert resolved.profile_id == selected.id
    assert resolved.deployment == exact
