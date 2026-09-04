from dataclasses import replace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.generation.profile import resolve_generation_profile
from ai_workshop.labs.rag.models.domain import (
    ModelDefinition,
    ModelKind,
    Profile,
    ProfileKind,
    ProfileModelBinding,
)

MODEL_ID = UUID("10000000-0000-0000-0000-000000000001")


def llm_model() -> ModelDefinition:
    return replace(
        ModelDefinition.create(
            kind=ModelKind.LLM,
            name="local-llm",
            version=3,
            config={
                "provider": "openai_compatible",
                "runtime_model": "runtime/exact-model",
                "data_policy": "local_only",
            },
        ),
        id=MODEL_ID,
    )


def generation_profile(*, model_id: UUID = MODEL_ID) -> Profile:
    return Profile.create(
        kind=ProfileKind.GENERATION,
        name="grounded-generation",
        version=2,
        config={
            "prompt_ref": "rag-answer-v1",
            "context_prompt_ref": "rag-contextualize-v1",
            "citation_mode": "required",
            "context_policy": {"max_history_turns": 6, "max_history_tokens": 1024},
            "generation": {
                "timeout_seconds": 30,
                "max_output_tokens": 512,
                "temperature": 0.1,
                "response_schema_version": 1,
            },
        },
        bindings=(ProfileModelBinding(ModelKind.LLM, model_id),),
    )


def test_resolver_keeps_exact_profile_model_and_policy_versions() -> None:
    resolved = resolve_generation_profile(generation_profile(), llm_model())

    assert resolved.profile_version == 2
    assert resolved.model_id == MODEL_ID
    assert resolved.model_version == 3
    assert resolved.runtime_model == "runtime/exact-model"
    assert resolved.context_policy.max_history_turns == 6
    assert resolved.max_output_tokens == 512


def test_resolver_rejects_model_outside_exact_profile_binding() -> None:
    with pytest.raises(ValueError, match="binding"):
        resolve_generation_profile(
            generation_profile(model_id=UUID("10000000-0000-0000-0000-000000000099")),
            llm_model(),
        )
