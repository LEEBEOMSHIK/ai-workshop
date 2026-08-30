from uuid import UUID

import pytest

from ai_workshop.labs.rag.embeddings.contracts import (
    EmbeddingModelConfig,
    EmbeddingValidationError,
)
from ai_workshop.labs.rag.models.domain import ModelDefinition, ModelKind, freeze_json

MODEL_ID = UUID("00000000-0000-0000-0000-000000000101")


def model_definition(**overrides: object) -> ModelDefinition:
    values: dict[str, object] = {
        "repo_id": "intfloat/multilingual-e5-base",
        "revision": "d128750597153bb5987e10b1c3493a34e5a4502a",
        "dimension": 768,
        "max_tokens": 512,
        "query_prefix": "query: ",
        "document_prefix": "passage: ",
        "normalize": True,
        "device": "cpu",
        "dtype": "float32",
        "output_mode": "dense",
        "data_policy": "local_only",
    }
    values.update(overrides)
    config = freeze_json(values)  # type: ignore[arg-type]
    assert not isinstance(config, tuple)
    return ModelDefinition(MODEL_ID, ModelKind.EMBEDDING, "multilingual-e5-base", 1, config)


def test_embedding_config_preserves_pinned_local_definition_and_profile_batch_size() -> None:
    config = EmbeddingModelConfig.from_definition(
        model_definition(), profile_config={"batch_size": 24}
    )

    assert config.repo_id == "intfloat/multilingual-e5-base"
    assert config.revision == "d128750597153bb5987e10b1c3493a34e5a4502a"
    assert config.dimension == 768
    assert config.max_tokens == 512
    assert config.query_prefix == "query: "
    assert config.document_prefix == "passage: "
    assert config.normalize is True
    assert config.device == "cpu"
    assert config.dtype == "float32"
    assert config.output_mode == "dense"
    assert config.data_policy == "local_only"
    assert config.batch_size == 24


@pytest.mark.parametrize(
    "missing",
    [
        "repo_id",
        "revision",
        "dimension",
        "max_tokens",
        "query_prefix",
        "document_prefix",
        "normalize",
        "device",
        "dtype",
        "output_mode",
        "data_policy",
    ],
)
def test_embedding_definition_rejects_each_missing_required_field(missing: str) -> None:
    definition = model_definition()
    values = dict(definition.config)
    del values[missing]
    invalid = ModelDefinition(
        definition.id,
        definition.kind,
        definition.name,
        definition.version,
        freeze_json(values),  # type: ignore[arg-type]
    )

    with pytest.raises(EmbeddingValidationError, match=missing):
        EmbeddingModelConfig.from_definition(invalid, profile_config={"batch_size": 16})


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"revision": "main"}, "40-character"),
        ({"revision": "a" * 39}, "40-character"),
        ({"data_policy": "external_allowed"}, "local_only"),
        ({"output_mode": "sparse"}, "dense"),
        ({"dimension": 0}, "dimension"),
        ({"max_tokens": 0}, "max_tokens"),
        ({"normalize": False}, "normalized"),
    ],
)
def test_embedding_definition_rejects_unpinned_or_nonlocal_dense_contract(
    overrides: dict[str, object], message: str
) -> None:
    with pytest.raises(EmbeddingValidationError, match=message):
        EmbeddingModelConfig.from_definition(
            model_definition(**overrides), profile_config={"batch_size": 16}
        )


@pytest.mark.parametrize("profile_config", [{}, {"batch_size": 0}, {"batch_size": "16"}])
def test_embedding_batch_size_must_come_from_profile_as_positive_integer(
    profile_config: dict[str, object],
) -> None:
    with pytest.raises(EmbeddingValidationError, match="batch_size"):
        EmbeddingModelConfig.from_definition(model_definition(), profile_config=profile_config)
