"""A committed terminal parent may close only its running persistence metadata."""

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ai_workshop.labs.rag.conversations.models import ConversationTurnRecord
from ai_workshop.labs.rag.evaluation.generative_models import GenerativeAttemptRecord
from ai_workshop.labs.rag.executions.contextualization import ContextualizationObservation
from ai_workshop.labs.rag.executions.domain import (
    STAGES,
    ExecutionOutcome,
    OperationTiming,
    SelectionObservation,
    StageObservation,
)
from ai_workshop.labs.rag.executions.history_selection import HistorySelectionObservation
from ai_workshop.labs.rag.executions.models import ExecutionRecord
from ai_workshop.labs.rag.executions.repository import SqlAlchemyExecutionRecorder


def setup_recorder(status="completed", parent_kind="conversation"):
    started = datetime(2026, 1, 1, tzinfo=UTC)
    end = StageObservation(
        stage="persistence", state="completed", started_at=started,
        ended_at=started + timedelta(milliseconds=12), duration_ms=12.0, operations=[],
    )
    row = ExecutionRecord(
        id=uuid4(), actor_id=uuid4(), turn_id=uuid4(), status=status,
        answer_status="answered" if status == "completed" else None,
        error_code=None if status == "completed" else "synthetic_failure",
        ended_at=started + timedelta(milliseconds=10), complete=False,
        stages={stage: {"state": "completed"} for stage in STAGES},
    )
    row.stages["persistence"] = StageObservation(
        stage="persistence", state="running", started_at=started, operations=[],
    ).model_dump(mode="json")
    parent = ConversationTurnRecord(id=row.turn_id, status=status)
    if parent_kind == "evaluation":
        row.turn_id, row.evaluation_attempt_id = None, uuid4()
        parent = GenerativeAttemptRecord(
            id=row.evaluation_attempt_id, execution_id=row.id, run_id=uuid4(), status=status,
        )
    session = AsyncMock(spec=AsyncSession)
    session.scalar.side_effect = [row, parent]
    sessions = MagicMock()
    sessions.begin.return_value.__aenter__.return_value = session
    return SqlAlchemyExecutionRecorder(sessions), row, parent, session, end


@pytest.mark.parametrize("status", ["completed", "failed", "cancelled", "interrupted"])
async def test_committed_terminal_turn_closes_running_persistence_without_rewriting_outcome(status):
    recorder, row, _, session, end = setup_recorder(status)
    terminal = row.status, row.answer_status, row.error_code, row.ended_at
    before = deepcopy(row.stages)

    await recorder.record(row.id, end)

    assert row.stages["persistence"]["state"] == "completed"
    assert row.stages["persistence"]["duration_ms"] == 12.0
    assert {k: v for k, v in row.stages.items() if k != "persistence"} == {
        k: v for k, v in before.items() if k != "persistence"
    }
    assert row.complete is False
    assert (row.status, row.answer_status, row.error_code, row.ended_at) == terminal
    session.scalar.side_effect = [row]
    await recorder.finish(row.id, ExecutionOutcome(state=status))
    assert row.complete is True
    assert (row.status, row.answer_status, row.error_code, row.ended_at) == terminal


@pytest.mark.parametrize("previous", [None, "pending", "completed", "failed", "skipped"])
async def test_cancelled_execution_does_not_invent_or_replace_persistence(previous):
    recorder, row, _, _, end = setup_recorder("cancelled")
    if previous is None:
        del row.stages["persistence"]
    else:
        row.stages["persistence"]["state"] = previous
    before = deepcopy(row.stages)
    await recorder.record(row.id, end)
    assert row.stages == before


@pytest.mark.parametrize("change", [
    {"state": "failed"}, {"state": "running"}, {"state": "skipped"},
    {"started_at": None}, {"started_at": datetime(2026, 1, 2, tzinfo=UTC)},
    {"ended_at": None}, {"ended_at": datetime(2025, 12, 31, tzinfo=UTC)},
    {"duration_ms": None}, {"selection": SelectionObservation(selected_count=1)},
    {"operations": [OperationTiming(
        name="retrieval.sources", duration_ms=1.0, calls=1, failures=0, items=1, reused_items=0,
    )]},
])
@pytest.mark.parametrize("parent_kind", ["conversation", "evaluation"])
async def test_terminal_persistence_rejects_unmatched_or_noncompletion_payload(change, parent_kind):
    recorder, row, _, _, end = setup_recorder(parent_kind=parent_kind)
    before = deepcopy(row.stages)
    await recorder.record(row.id, end.model_copy(update=change))
    assert row.stages == before


@pytest.mark.parametrize("parent_status", [None, "running", "failed"])
@pytest.mark.parametrize("parent_kind", ["conversation", "evaluation"])
async def test_terminal_persistence_requires_available_matching_parent(parent_status, parent_kind):
    recorder, row, parent, session, end = setup_recorder(parent_kind=parent_kind)
    if parent_status is None:
        session.scalar.side_effect = [row, None]
    else:
        parent.status = parent_status
    before = deepcopy(row.stages)
    await recorder.record(row.id, end)
    assert row.stages == before


@pytest.mark.parametrize("status", ["completed", "failed", "interrupted"])
async def test_committed_terminal_attempt_closes_only_persistence_without_rewriting_result(status):
    recorder, row, parent, session, end = setup_recorder(status, "evaluation")
    terminal = row.status, row.answer_status, row.error_code, row.ended_at
    parent_before = deepcopy(parent.__dict__)
    before = deepcopy(row.stages)
    await recorder.record(row.id, end)
    assert row.stages["persistence"] == end.model_dump(mode="json")
    assert {k: v for k, v in row.stages.items() if k != "persistence"} == {
        k: v for k, v in before.items() if k != "persistence"
    }
    assert row.complete is False
    assert (row.status, row.answer_status, row.error_code, row.ended_at) == terminal
    assert {k: v for k, v in parent.__dict__.items() if k != "_sa_instance_state"} == {
        k: v for k, v in parent_before.items() if k != "_sa_instance_state"
    }
    session.scalar.side_effect = [row]
    await recorder.finish(row.id, ExecutionOutcome(state=status))
    assert row.complete is True
    assert (row.status, row.answer_status, row.error_code, row.ended_at) == terminal


async def test_terminal_evaluation_parent_lookup_binds_exact_attempt_execution_owner():
    recorder, row, _, session, end = setup_recorder(parent_kind="evaluation")
    await recorder.record(row.id, end)
    statement = session.scalar.await_args_list[1].args[0].compile()
    assert row.evaluation_attempt_id in statement.params.values()
    assert row.id in statement.params.values()
    assert row.actor_id in statement.params.values()
    assert "rag_generative_attempts.id =" in str(statement)
    assert "rag_generative_attempts.execution_id =" in str(statement)
    assert "rag_generative_runs.owner_id =" in str(statement)
    assert "rag_generative_runs.status =" not in str(statement)
    assert "claim_token =" not in str(statement)
    assert "FOR UPDATE" not in str(statement)


@pytest.mark.parametrize("parents", ["both", "neither"])
async def test_terminal_persistence_rejects_ambiguous_or_missing_parent_relationship(parents):
    recorder, row, _, session, end = setup_recorder()
    if parents == "both":
        row.evaluation_attempt_id = uuid4()
    else:
        row.turn_id = None
    before = deepcopy(row.stages)
    await recorder.record(row.id, end)
    assert row.stages == before
    assert session.scalar.await_count == 1


async def test_cancelled_evaluation_cannot_claim_started_persistence():
    recorder, row, _, session, end = setup_recorder("cancelled", "evaluation")
    before = deepcopy(row.stages)
    await recorder.record(row.id, end)
    assert row.stages == before
    assert session.scalar.await_count == 1


@pytest.mark.parametrize("previous", [None, "pending", "completed", "failed", "skipped"])
async def test_terminal_attempt_does_not_invent_or_replace_persistence(previous):
    recorder, row, _, _, end = setup_recorder("failed", "evaluation")
    if previous is None:
        del row.stages["persistence"]
    else:
        row.stages["persistence"]["state"] = previous
    before = deepcopy(row.stages)
    await recorder.record(row.id, end)
    assert row.stages == before


async def test_terminal_parent_lookup_is_owned_live_and_does_not_reverse_lock_order():
    recorder, row, _, session, end = setup_recorder()
    await recorder.record(row.id, end)
    statement = session.scalar.await_args_list[1].args[0].compile()
    assert row.turn_id in statement.params.values()
    assert row.actor_id in statement.params.values()
    assert "rag_conversations.owner_id =" in str(statement)
    assert "rag_conversations.deleted_at IS NULL" in str(statement)
    assert "FOR UPDATE" not in str(statement)


@pytest.mark.parametrize("parent_kind", ["conversation", "evaluation"])
async def test_late_evidence_and_duplicate_persistence_cannot_replace_observations(parent_kind):
    recorder, row, _, session, end = setup_recorder(parent_kind=parent_kind)
    await recorder.record(row.id, end)
    before = deepcopy(row.stages)
    session.scalar.side_effect = [row, row]
    await recorder.record(row.id, StageObservation(
        stage="selection", state="completed", selection=SelectionObservation(selected_count=1),
    ))
    await recorder.record(row.id, end.model_copy(update={"duration_ms": 999.0}))
    assert row.stages == before


@pytest.mark.parametrize("field,value", [
    ("history_selection", HistorySelectionObservation(
        max_history_messages=2, max_history_tokens=10,
        input_message_count=0, selected_message_count=0, messages=(),
    )),
    ("contextualization", ContextualizationObservation()),
])
@pytest.mark.parametrize("parent_kind", ["conversation", "evaluation"])
async def test_terminal_persistence_rejects_body_or_history_payloads(field, value, parent_kind):
    recorder, row, _, _, end = setup_recorder(parent_kind=parent_kind)
    before = deepcopy(row.stages)
    # model_copy skips Pydantic validation, so the repository must keep its own fence.
    await recorder.record(row.id, end.model_copy(update={field: value}))
    assert row.stages == before


async def test_persistence_closure_does_not_hide_another_missing_observation():
    recorder, row, _, session, end = setup_recorder()
    del row.stages["retrieval"]
    await recorder.record(row.id, end)
    assert row.stages["persistence"]["state"] == "completed"
    session.scalar.side_effect = [row]
    await recorder.finish(row.id, ExecutionOutcome(state="completed"))
    assert row.complete is False


async def test_failed_evaluation_persistence_closure_does_not_invent_unobserved_stages():
    recorder, row, _, session, end = setup_recorder("failed", "evaluation")
    del row.stages["history"]
    del row.stages["citation_validation"]
    row.stages["generation"] = {"state": "failed"}
    await recorder.record(row.id, end)
    assert row.stages["persistence"]["state"] == "completed"
    session.scalar.side_effect = [row]
    await recorder.finish(row.id, ExecutionOutcome(state="failed"))
    assert row.complete is False
    assert row.status == "failed"
    assert row.error_code == "synthetic_failure"
    assert "history" not in row.stages and "citation_validation" not in row.stages
