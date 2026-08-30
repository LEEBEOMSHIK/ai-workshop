import math
from dataclasses import replace
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.evaluation.domain import (
    CandidateStatus,
    EvaluationMetrics,
    EvaluationPolicy,
    EvaluationRunStatus,
    PromotionEvidence,
    PromotionGate,
    PromotionPolicyError,
)


def policy() -> EvaluationPolicy:
    return EvaluationPolicy.create(
        owner_id=uuid4(),
        dataset_snapshot_id=uuid4(),
        version=1,
        metric_definition_version=1,
        retrieval_k=3,
        recall_at_k=0.60,
        mrr=0.50,
        ndcg=0.55,
        supported_precision=0.90,
        max_false_grounding_rate=0.10,
        min_highlight_iou=0.70,
        max_p50_latency_ms=500.0,
        max_p95_latency_ms=1000.0,
        max_access_leaks=0,
        required_reproducibility=1.0,
    )


def metrics() -> EvaluationMetrics:
    return EvaluationMetrics(
        recall_at_k=0.75,
        mrr=0.70,
        ndcg=0.65,
        supported_precision=0.95,
        false_grounding_rate=0.05,
        highlight_iou=0.80,
        p50_latency_ms=400.0,
        p95_latency_ms=900.0,
        access_leaks=0,
        reproducibility=1.0,
    )


def evidence() -> PromotionEvidence:
    configuration_version_id = uuid4()
    return PromotionEvidence(
        configuration_version_id=configuration_version_id,
        evaluated_configuration_version_id=configuration_version_id,
        metric_definition_version=1,
        retrieval_k=3,
        run_status=EvaluationRunStatus.COMPLETED,
        candidate_status=CandidateStatus.COMPLETED,
        failure=None,
        metrics=metrics(),
    )


def test_policy_requires_every_finite_threshold_and_exact_security_values() -> None:
    with pytest.raises(PromotionPolicyError, match="max_access_leaks"):
        replace(policy(), max_access_leaks=1).validate()
    with pytest.raises(PromotionPolicyError, match="required_reproducibility"):
        replace(policy(), required_reproducibility=0.99).validate()
    with pytest.raises(PromotionPolicyError, match="finite"):
        replace(policy(), max_p95_latency_ms=math.inf).validate()
    with pytest.raises(PromotionPolicyError, match="bounded"):
        replace(policy(), recall_at_k=-0.01).validate()
    with pytest.raises(PromotionPolicyError, match="retrieval_k"):
        replace(policy(), retrieval_k=0).validate()
    with pytest.raises(PromotionPolicyError, match="metric definition"):
        replace(policy(), metric_definition_version=2).validate()


@pytest.mark.parametrize(
    "broken",
    [
        lambda item: replace(item, run_status=EvaluationRunStatus.RUNNING),
        lambda item: replace(item, candidate_status=CandidateStatus.FAILED),
        lambda item: replace(item, failure="embedding unavailable"),
        lambda item: replace(item, metrics=None),
        lambda item: replace(item, evaluated_configuration_version_id=uuid4()),
        lambda item: replace(item, metric_definition_version=2),
        lambda item: replace(item, retrieval_k=10),
    ],
)
def test_promotion_fails_closed_for_incomplete_failed_or_wrong_version_evidence(
    broken: object,
) -> None:
    mutate = broken
    assert callable(mutate)
    assert PromotionGate.qualifies(policy(), mutate(evidence())) is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("recall_at_k", 0.59),
        ("mrr", 0.49),
        ("ndcg", 0.54),
        ("supported_precision", 0.89),
        ("false_grounding_rate", 0.11),
        ("highlight_iou", 0.69),
        ("p50_latency_ms", 501.0),
        ("p95_latency_ms", 1001.0),
        ("access_leaks", 1),
        ("reproducibility", 0.999999999),
    ],
)
def test_every_policy_metric_independently_blocks_promotion(
    field: str,
    value: float,
) -> None:
    item = evidence()
    assert item.metrics is not None
    failed_metrics = replace(item.metrics, **{field: value})

    assert PromotionGate.qualifies(
        policy(), replace(item, metrics=failed_metrics)
    ) is False


def test_no_policy_never_qualifies_and_exact_boundary_values_do() -> None:
    item = evidence()
    exact = EvaluationMetrics(
        recall_at_k=0.60,
        mrr=0.50,
        ndcg=0.55,
        supported_precision=0.90,
        false_grounding_rate=0.10,
        highlight_iou=0.70,
        p50_latency_ms=500.0,
        p95_latency_ms=1000.0,
        access_leaks=0,
        reproducibility=1.0,
    )

    assert PromotionGate.qualifies(None, item) is False
    assert PromotionGate.qualifies(policy(), replace(item, metrics=exact)) is True
