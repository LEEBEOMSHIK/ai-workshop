from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.configurations.domain import (
    ConfigurationValidationError,
    EvaluationAcceptanceResult,
)
from ai_workshop.labs.rag.configurations.service import RagConfigurationService
from ai_workshop.labs.rag.evaluation.domain import CandidateStatus, EvaluationRunStatus
from ai_workshop.labs.rag.models.domain import EvaluationState
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.configurations.test_configuration import _configuration
from tests.unit.labs.rag.evaluation.test_promotion_policy import evidence, policy


@pytest.mark.parametrize("is_default", [False, True])
def test_acceptance_preserves_exact_version_and_default(is_default: bool) -> None:
    configuration = replace(_configuration(), is_default=is_default)
    proof = replace(
        evidence(),
        configuration_version_id=configuration.version_id,
        evaluated_configuration_version_id=configuration.version_id,
    )

    accepted = configuration.with_passed_evaluation(policy=policy(), evidence=proof)

    assert accepted == replace(configuration, evaluation_state=EvaluationState.PASSED)
    assert configuration.evaluation_state is EvaluationState.PENDING
    assert configuration.as_default(policy=policy(), evidence=proof).is_default is True


@pytest.mark.parametrize(
    "change",
    [
        {"configuration_version_id": uuid4()},
        {"evaluated_configuration_version_id": uuid4()},
        {"run_status": EvaluationRunStatus.FAILED},
        {"candidate_status": CandidateStatus.FAILED},
        {"failure": "synthetic failure"},
        {"metrics": None},
        {"retrieval_k": 4},
        {"metric_definition_version": 2},
    ],
)
def test_acceptance_rejects_invalid_evidence_without_mutation(change: dict) -> None:
    configuration = _configuration()
    proof = replace(
        evidence(),
        configuration_version_id=configuration.version_id,
        evaluated_configuration_version_id=configuration.version_id,
    )
    with pytest.raises(ConfigurationValidationError):
        configuration.with_passed_evaluation(policy=policy(), evidence=replace(proof, **change))
    assert configuration.evaluation_state is EvaluationState.PENDING
    assert configuration.is_default is False


def test_acceptance_requires_policy() -> None:
    configuration = _configuration()
    proof = replace(
        evidence(),
        configuration_version_id=configuration.version_id,
        evaluated_configuration_version_id=configuration.version_id,
    )
    with pytest.raises(ConfigurationValidationError):
        configuration.with_passed_evaluation(policy=None, evidence=proof)


@pytest.mark.parametrize(
    "field,value",
    [
        ("recall_at_k", 0.59),
        ("mrr", 0.49),
        ("ndcg", 0.54),
        ("supported_precision", 0.89),
        ("false_grounding_rate", 0.11),
        ("highlight_iou", 0.69),
        ("p50_latency_ms", 501),
        ("p95_latency_ms", 1001),
        ("access_leaks", 1),
        ("reproducibility", 0.99),
    ],
)
def test_acceptance_keeps_every_existing_quality_gate(field, value):
    configuration = _configuration()
    proof = evidence()
    proof = replace(
        proof,
        configuration_version_id=configuration.version_id,
        evaluated_configuration_version_id=configuration.version_id,
        metrics=replace(proof.metrics, **{field: value}),
    )
    with pytest.raises(ConfigurationValidationError):
        configuration.with_passed_evaluation(policy=policy(), evidence=proof)


@pytest.mark.parametrize("fails", [False, True])
async def test_service_commits_only_after_exact_acceptance(fails: bool) -> None:
    config = _configuration()
    run_id, policy_id = uuid4(), uuid4()
    events = []
    result = EvaluationAcceptanceResult(config, run_id, policy_id)

    class Repository:
        async def accept_evaluation(
            self, configuration_id, version_id, evaluation_run_id, actor_id
        ):
            assert (configuration_id, version_id, evaluation_run_id, actor_id) == (
                config.id,
                config.version_id,
                run_id,
                config.owner_id,
            )
            events.append("accepted" if not fails else "rejected")
            if fails:
                raise AppError("evaluation_policy_required", "Synthetic rejection.", 409)
            return result

    async def commit():
        events.append("committed")

    service = RagConfigurationService(Repository(), object(), commit=commit)
    if fails:
        with pytest.raises(AppError):
            await service.accept_evaluation(config.id, config.version_id, run_id, config.owner_id)
        assert events == ["rejected"]
    else:
        assert (
            await service.accept_evaluation(config.id, config.version_id, run_id, config.owner_id)
            == result
        )
        assert events == ["accepted", "committed"]
