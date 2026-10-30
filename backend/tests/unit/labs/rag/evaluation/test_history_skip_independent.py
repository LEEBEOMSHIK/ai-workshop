"""History observation must not alter frozen evaluation or failure boundaries."""

import asyncio

import pytest

from ai_workshop.labs.rag.evaluation import generative_workflow as module
from tests.unit.labs.rag.evaluation.test_generative_termination_workflow import workflow_fixture


@pytest.mark.parametrize("mode,error", [
    ("normal", None),
    ("confirmed_validation", "citation_validation_failed"),
    ("predispatch_timeout", "provider_timeout"),
    ("pending_timeout", "provider_termination_unconfirmed"),
    ("cancel_pending", "provider_termination_unconfirmed"),
    ("cancel_predispatch", None),
])
@pytest.mark.parametrize("broken_history_observation", [False, True])
async def test_history_skip_precedes_attempt_end_without_changing_failures_or_retry(
    monkeypatch, caplog, mode, error, broken_history_observation,
):
    env = workflow_fixture(monkeypatch, mode)
    original_recorder = module.SqlAlchemyExecutionRecorder
    original_complete = env.workflow.repository.complete_attempt
    history_events = []
    persistence_events = []

    def recorder(sessions):
        value = original_recorder(sessions)
        original_record = value.record

        async def record(execution_id, observation):
            if observation.stage == "history":
                history_events.append((execution_id, observation))
                assert execution_id not in persistence_events
                if broken_history_observation:
                    raise RuntimeError("SYNTHETIC_PRIVATE_HISTORY_WRITE_FAILURE")
            await original_record(execution_id, observation)

        value.record = record
        return value

    async def complete(attempt_id, token, result, *, error_code):
        execution_id = next(item.execution_id for item in env.attempts if item.id == attempt_id)
        assert [identity for identity, _ in history_events].count(execution_id) == 1
        persistence_events.append(execution_id)
        await original_complete(attempt_id, token, result, error_code=error_code)

    monkeypatch.setattr(module, "SqlAlchemyExecutionRecorder", recorder)
    monkeypatch.setattr(env.workflow.repository, "complete_attempt", complete)
    if mode in {"cancel_pending", "cancel_predispatch"}:
        with pytest.raises(asyncio.CancelledError):
            await env.workflow._execute_claimed(env.run_id, env.token)
    else:
        await env.workflow._execute_claimed(env.run_id, env.token)

    expected_calls = 1 if mode in {
        "pending_timeout", "cancel_pending", "cancel_predispatch",
    } else 2
    assert len(env.calls) == len(history_events) == expected_calls
    for _, observation in history_events:
        assert observation.state == "skipped"
        assert observation.reason == "not_executed"
        assert observation.started_at is None
        assert observation.duration_ms is None
        assert observation.history_selection is None
    if mode == "cancel_predispatch":
        assert env.results == env.finishes == []
    else:
        assert env.results[0][2] == error
        assert len(env.results) == expected_calls
        assert all(item.outcome.complete == (not broken_history_observation)
                   for item in env.recorders)
    if error == "provider_termination_unconfirmed":
        assert env.finishes == []
    assert "SYNTHETIC_PRIVATE_HISTORY_WRITE_FAILURE" not in caplog.text
