from uuid import uuid4

import pytest

from ai_workshop.labs.rag.generation.domain import ContextPolicy, GenerationProfile


def make_profile(**overrides: object) -> GenerationProfile:
    values: dict[str, object] = {
        "profile_id": uuid4(),
        "profile_name": "로컬 생성",
        "profile_version": 2,
        "model_id": uuid4(),
        "model_name": "등록된 로컬 LLM",
        "model_version": 3,
        "runtime_model": "registry/runtime-model",
        "prompt_ref": "rag-answer-v1",
        "context_prompt_ref": "rag-contextualize-v1",
        "context_policy": ContextPolicy(max_history_turns=6, max_history_tokens=1024),
        "timeout_seconds": 30.0,
        "max_output_tokens": 512,
        "temperature": 0.1,
        "response_schema_version": 1,
    }
    values.update(overrides)
    return GenerationProfile(**values)  # type: ignore[arg-type]


def test_generation_profile_preserves_exact_model_and_versioned_prompts() -> None:
    profile = make_profile()

    assert profile.profile_version == 2
    assert profile.model_version == 3
    assert profile.runtime_model == "registry/runtime-model"
    assert profile.prompt_ref == "rag-answer-v1"
    assert profile.context_prompt_ref == "rag-contextualize-v1"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"prompt_ref": ""}, "prompt"),
        ({"context_prompt_ref": ""}, "context prompt"),
        ({"timeout_seconds": 0.0}, "timeout"),
        ({"max_output_tokens": 0}, "output token"),
        ({"temperature": -0.1}, "temperature"),
        ({"temperature": 2.1}, "temperature"),
        ({"response_schema_version": 0}, "schema"),
    ],
)
def test_generation_profile_rejects_invalid_runtime_contract(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        make_profile(**overrides)
