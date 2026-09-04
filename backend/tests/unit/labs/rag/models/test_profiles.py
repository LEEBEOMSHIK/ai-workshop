from uuid import uuid4

import pytest

from ai_workshop.labs.rag.models.domain import (
    EvaluationState,
    ModelDefinition,
    ModelKind,
    Profile,
    ProfileKind,
    ProfileModelBinding,
    ProfileValidationError,
)


def binding(role: ModelKind) -> ProfileModelBinding:
    return ProfileModelBinding(role=role, model_id=uuid4())


def test_model_configuration_is_immutable_and_rejects_literal_secrets() -> None:
    model = ModelDefinition.create(
        kind=ModelKind.EMBEDDING,
        name="local-embedding",
        version=1,
        config={"dimension": 768, "credential_env": "EMBEDDING_CREDENTIAL"},
    )

    with pytest.raises(TypeError):
        model.config["dimension"] = 1024  # type: ignore[index]

    with pytest.raises(ProfileValidationError, match="environment variable"):
        ModelDefinition.create(
            kind=ModelKind.LLM,
            name="unsafe-llm",
            version=1,
            config={"api_key": "literal-secret"},
        )


def test_indexing_profile_requires_chunker_and_embedding() -> None:
    with pytest.raises(ProfileValidationError, match="chunker"):
        Profile.create(
            kind=ProfileKind.INDEXING,
            name="indexing-baseline",
            version=1,
            config={},
            bindings=(binding(ModelKind.EMBEDDING),),
        )

    profile = Profile.create(
        kind=ProfileKind.INDEXING,
        name="indexing-baseline",
        version=1,
        config={"chunker": {"name": "structure", "version": 1}},
        bindings=(binding(ModelKind.EMBEDDING),),
    )

    assert profile.kind is ProfileKind.INDEXING


def test_profile_configuration_is_deeply_immutable() -> None:
    profile = Profile.create(
        kind=ProfileKind.RETRIEVAL,
        name="bm25-baseline",
        version=1,
        config={"bm25": {"top_k": 30}},
        bindings=(),
    )

    bm25 = profile.config["bm25"]
    assert not isinstance(bm25, str)
    with pytest.raises(TypeError):
        bm25["top_k"] = 50  # type: ignore[index]


def test_dense_retrieval_requires_rrf_and_rejects_llm_binding() -> None:
    with pytest.raises(ProfileValidationError, match="RRF"):
        Profile.create(
            kind=ProfileKind.RETRIEVAL,
            name="hybrid",
            version=1,
            config={"bm25": {}, "dense": {}, "indexing_profile_id": str(uuid4())},
            bindings=(),
        )

    with pytest.raises(ProfileValidationError, match="LLM"):
        Profile.create(
            kind=ProfileKind.RETRIEVAL,
            name="invalid-llm-retrieval",
            version=1,
            config={"bm25": {}},
            bindings=(binding(ModelKind.LLM),),
        )


def test_generation_requires_llm_and_prompt_reference() -> None:
    with pytest.raises(ProfileValidationError, match="prompt"):
        Profile.create(
            kind=ProfileKind.GENERATION,
            name="generation-baseline",
            version=1,
            config={},
            bindings=(binding(ModelKind.LLM),),
        )


def test_llm_model_requires_local_openai_compatible_runtime_identity() -> None:
    model = ModelDefinition.create(
        kind=ModelKind.LLM,
        name="registered-local-llm",
        version=1,
        config={
            "provider": "openai_compatible",
            "runtime_model": "runtime/exact-model",
            "data_policy": "local_only",
        },
    )

    assert model.config["runtime_model"] == "runtime/exact-model"

    with pytest.raises(ProfileValidationError, match="local"):
        ModelDefinition.create(
            kind=ModelKind.LLM,
            name="external-llm",
            version=1,
            config={
                "provider": "external_provider",
                "runtime_model": "remote/model",
                "data_policy": "external",
            },
        )


def test_generation_profile_requires_complete_context_and_output_contract() -> None:
    llm = binding(ModelKind.LLM)
    valid_config = {
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
    }

    profile = Profile.create(
        kind=ProfileKind.GENERATION,
        name="local-grounded-generation",
        version=1,
        config=valid_config,
        bindings=(llm,),
    )

    assert profile.kind is ProfileKind.GENERATION

    for missing_key in ("context_prompt_ref", "citation_mode", "context_policy", "generation"):
        invalid = dict(valid_config)
        invalid.pop(missing_key)
        with pytest.raises(ProfileValidationError, match="generation profile"):
            Profile.create(
                kind=ProfileKind.GENERATION,
                name="incomplete-generation",
                version=1,
                config=invalid,
                bindings=(llm,),
            )


def test_generation_profile_requires_exactly_one_llm_binding() -> None:
    config = {
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
    }

    with pytest.raises(ProfileValidationError, match="exactly one"):
        Profile.create(
            kind=ProfileKind.GENERATION,
            name="duplicate-llm",
            version=1,
            config=config,
            bindings=(binding(ModelKind.LLM), binding(ModelKind.LLM)),
        )


def test_only_passed_profile_can_become_default() -> None:
    profile = Profile.create(
        kind=ProfileKind.RETRIEVAL,
        name="bm25",
        version=1,
        config={"bm25": {}},
        bindings=(),
        evaluation_state=EvaluationState.DRAFT,
    )

    with pytest.raises(ProfileValidationError, match="evaluation"):
        profile.as_default()
