from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from ai_workshop.labs.rag.evaluation import generative_read as reads
from ai_workshop.labs.rag.evaluation.generative import (
    ExpectedAnswerRule,
    GenerativeObservation,
    PrivateGenerativeResult,
)
from ai_workshop.labs.rag.executions.read_repository import SqlAlchemyMonitoringRepository
from ai_workshop.labs.rag.executions.schemas import ExecutionSearchRequest
from ai_workshop.labs.rag.executions.service import ExecutionReadService
from ai_workshop.labs.rag.generation.numeric_validation_batch import NumericValidationBatch


async def test_list_enumerates_ids_without_loading_discarded_entries():
    repository = MagicMock()
    repository.entries.side_effect = AssertionError("Full entries must not be enumerated")

    async def ids(actor):
        yield uuid4()

    repository.turn_ids = ids
    service = ExecutionReadService(repository, MagicMock())
    service._current_visible = AsyncMock(return_value=None)
    assert (await service.search(uuid4(), ExecutionSearchRequest())).total == 0
    service._current_visible.assert_awaited_once()


async def test_evaluation_filter_does_not_read_conversations():
    repository = MagicMock()
    repository.entries.side_effect = AssertionError("Excluded conversation reader")
    evaluations = SimpleNamespace(summaries=AsyncMock(return_value=[]))
    service = ExecutionReadService(repository, MagicMock(), evaluations)
    service._authorized = AsyncMock(side_effect=AssertionError("Excluded conversations"))
    assert (await service.search(uuid4(), ExecutionSearchRequest(kind="evaluation"))).total == 0
    evaluations.summaries.assert_awaited_once()


async def test_id_query_projects_only_turn_id_and_retains_owner_deleted_domain():
    actor, turn_id = uuid4(), uuid4()
    session = AsyncMock()
    session.scalars.return_value = MagicMock(all=lambda: [turn_id])
    factory = MagicMock()
    factory.return_value.__aenter__.return_value = session
    repository = SqlAlchemyMonitoringRepository(factory)
    assert [item async for item in repository.turn_ids(actor)] == [turn_id]
    query = session.scalars.call_args.args[0]
    assert len(query.selected_columns) == 1
    sql = str(query)
    assert "owner_id" in sql and "deleted_at IS NULL" in sql and "rag_domains" in sql
    assert actor in query.compile().params.values()
    assert "response" not in sql and "stages" not in sql


@pytest.mark.parametrize("list_only", [False, True])
@pytest.mark.parametrize("matching_review", [False, True])
async def test_run_projection_and_reviewer_digest_reuse(monkeypatch, list_only, matching_review):
    actor, run_id, case_id, attempt_id, execution_id, config_id = (uuid4() for _ in range(6))
    now = datetime.now(UTC)
    rule = ExpectedAnswerRule(version=1, expected_answer_status="insufficient_evidence")
    result = PrivateGenerativeResult(observation=GenerativeObservation(
        execution_id=execution_id, generation_status="insufficient_evidence",
    ))
    review = SimpleNamespace(
        attempt_id=attempt_id, result_digest=result.digest() if matching_review else "0" * 64,
        rule_digest=rule.digest(), status="failed", reviewer_id=actor, created_at=now,
        reason="Synthetic review",
    )
    run = SimpleNamespace(
        id=run_id, owner_id=actor, snapshot={"sources": []}, dataset_snapshot_id=uuid4(),
        policy_id=uuid4(), expected_rules={str(case_id): rule.model_dump(mode="json")},
        rules_digest="0" * 64, status="completed", created_at=now, repetition_count=2,
        cancelled_by=None, cancelled_at=None, cancellation_reason=None,
    )
    attempt = SimpleNamespace(
        id=attempt_id, case_id=case_id, result=result.model_dump(mode="json"),
        status="completed", execution_id=execution_id, configuration_version_id=config_id,
        repetition=1, attempt_number=1, result_digest=result.digest(), error_code=None,
    )
    session = AsyncMock()
    session.scalar.return_value = run
    session.scalars.side_effect = [
        MagicMock(all=lambda: [SimpleNamespace(id=case_id, query_bytes=b"synthetic")]),
        MagicMock(all=lambda: [attempt]), MagicMock(all=lambda: [execution_id]),
        MagicMock(all=lambda: [review]),
    ]
    visible = AsyncMock(return_value=True)
    verify = AsyncMock()
    batch = MagicMock(spec=NumericValidationBatch)
    batch.revalidate = AsyncMock()
    prepare = AsyncMock(return_value=batch)
    monkeypatch.setattr(NumericValidationBatch, "prepare", prepare)
    monkeypatch.setattr(reads, "visible_run", visible)
    monkeypatch.setattr(reads, "verify_numeric_views", verify)
    monkeypatch.setattr(reads, "frozen_generation_profile_id", lambda *args: uuid4())
    original_digest = PrivateGenerativeResult.digest
    digest_calls = []

    def counted_digest(self):
        digest_calls.append(1)
        return original_digest(self)

    monkeypatch.setattr(PrivateGenerativeResult, "digest", counted_digest)
    kwargs = {"list_only": True} if list_only else {}
    view = await reads.run_detail(session, actor, run_id, **kwargs)
    assert len(digest_calls) == 1
    assert view.attempts[0].judgment.provenance == ("reviewer" if matching_review else "rule")
    assert visible.await_count == 2
    verify.assert_awaited_once()
    if list_only:
        prepare.assert_awaited_once_with(session, actor_id=actor, execution_ids=[execution_id])
        assert verify.await_args.args[0] is batch
        batch.revalidate.assert_awaited_once()
    else:
        prepare.assert_not_awaited()
    run_sql = str(session.scalar.call_args.args[0])
    attempt_sql = str(session.scalars.call_args_list[1].args[0])
    assert ("snapshot_bytes" in run_sql) is (not list_only)
    assert ("result_bytes" in attempt_sql) is (not list_only)
