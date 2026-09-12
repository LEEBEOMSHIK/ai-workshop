from dataclasses import replace
from uuid import UUID

import pytest

from ai_workshop.labs.rag.deployments.domain import ProviderKind
from ai_workshop.labs.rag.generation.domain import (
    GeneratedClaim,
    GenerationStatus,
    StructuredGeneration,
)
from ai_workshop.labs.rag.generation.execution import (
    ProviderExecutionMetadata,
    ProviderGenerationResult,
)


def _execution() -> ProviderExecutionMetadata:
    return ProviderExecutionMetadata(
        ProviderKind.OPENAI_RESPONSES, "synthetic-model", UUID(int=1), 7, 3, 10
    )


def _answer() -> StructuredGeneration:
    return StructuredGeneration(1, (GeneratedClaim("Synthetic fact.", (UUID(int=2),)),))


def test_execution_observed_identity_is_optional_not_requested_default():
    assert _execution().observed_provider_model_id is None
    assert (
        replace(
            _execution(), observed_provider_model_id="synthetic-model"
        ).observed_provider_model_id
        == "synthetic-model"
    )


@pytest.mark.parametrize("observed", ["", " model", "model\n", "x" * 201, True, 12])
def test_execution_rejects_unbounded_or_unsafe_observed_identity(observed):
    with pytest.raises(ValueError):
        replace(_execution(), observed_provider_model_id=observed)


def test_legacy_answer_constructor_defaults_to_answered() -> None:
    result = ProviderGenerationResult(_answer(), _execution())
    assert result.status is GenerationStatus.ANSWERED
    assert result.generation is not None
    assert result.generation.schema_version == 1


def test_explicit_insufficient_evidence_has_no_generation() -> None:
    result = ProviderGenerationResult(
        None, _execution(), status=GenerationStatus.INSUFFICIENT_EVIDENCE
    )
    assert result.status is GenerationStatus.INSUFFICIENT_EVIDENCE
    assert result.generation is None


@pytest.mark.parametrize(
    ("status", "generation"),
    [
        (GenerationStatus.ANSWERED, None),
        (GenerationStatus.ANSWERED, StructuredGeneration(1, ())),
        (GenerationStatus.INSUFFICIENT_EVIDENCE, _answer()),
        (GenerationStatus.NOT_REQUESTED, None),
        (GenerationStatus.CITATION_VALIDATION_FAILED, None),
        ("answered", _answer()),
    ],
)
def test_invalid_provider_result_combinations_are_rejected(
    status: GenerationStatus, generation: StructuredGeneration | None
) -> None:
    with pytest.raises(ValueError, match="generation result"):
        ProviderGenerationResult(generation, _execution(), status=status)
