from uuid import UUID

import pytest

from ai_workshop.labs.rag.evaluation.generative import (
    ExpectedAnswerRule,
    GenerativeObservation,
    PrivateGenerativeResult,
    evaluate_generative,
    judge_propositions,
)


def observation(**values):
    return GenerativeObservation(
        execution_id=UUID(int=1),
        retrieved_evidence_ids=(UUID(int=2),),
        selected_evidence_ids=(UUID(int=2),),
        cited_evidence_ids=(UUID(int=2),),
        generation_status="answered",
        citation_valid=True,
        **values,
    )


def rule(**values):
    return ExpectedAnswerRule(
        version=1,
        expected_answer_status="answered",
        required_evidence_groups=((UUID(int=2),),),
        **values,
    )


def test_valid_citation_does_not_establish_correctness():
    metrics = evaluate_generative(observation(), rule(), None)
    assert metrics.context_coverage == 1.0
    assert metrics.citation_valid is True
    assert metrics.correctness == "unreviewed"
    assert metrics.abstention_correct is None


def test_negative_answered_case_fails_abstention():
    metrics = evaluate_generative(
        observation(),
        ExpectedAnswerRule(
            version=1,
            expected_answer_status="insufficient_evidence",
        ),
        None,
    )
    assert metrics.abstention_correct is False
    assert metrics.correctness == "failed"


def test_missing_required_context_fails_coverage():
    metrics = evaluate_generative(
        observation().model_copy(update={"selected_evidence_ids": ()}),
        rule(),
        None,
    )
    assert metrics.context_coverage == 0


def test_rule_judgment_is_bound_to_exact_private_result():
    answer = PrivateGenerativeResult(observation=observation(), answer="Payment in seven days.")
    expected = rule(required_propositions=("seven days",), forbidden_propositions=("one day",))
    judgment = judge_propositions(answer, expected)
    assert judgment.status == "passed"
    assert judgment.provenance == "rule"
    assert judgment.result_digest == answer.digest()
    changed = answer.model_copy(update={"answer": "Payment in one day."})
    assert judge_propositions(changed, expected).status == "failed"
    assert judge_propositions(changed, expected).result_digest != judgment.result_digest


def test_no_propositions_cannot_invent_content_pass():
    answer = PrivateGenerativeResult(observation=observation(), answer="Unsupported content.")
    assert judge_propositions(answer, rule()).status == "unreviewed"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1])
def test_invalid_observation_duration_rejected(bad):
    with pytest.raises(ValueError):
        observation(duration_ms=bad)


@pytest.mark.asyncio
async def test_duplicate_delivery_does_not_execute_claimed_pipeline_twice():
    from unittest.mock import AsyncMock
    from uuid import uuid4

    from ai_workshop.config import Settings
    from ai_workshop.labs.rag.evaluation.generative_workflow import GenerativeWorkflow

    workflow = GenerativeWorkflow(None, Settings())
    workflow.repository.claim_run = AsyncMock(side_effect=[uuid4(), None])
    workflow._execute_claimed = AsyncMock()
    run_id = uuid4()
    await workflow.run(run_id)
    await workflow.run(run_id)
    workflow._execute_claimed.assert_awaited_once()
