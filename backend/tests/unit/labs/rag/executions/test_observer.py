from uuid import uuid4

import pytest

from ai_workshop.labs.rag.executions.domain import ExecutionIdentity, ExecutionOutcome
from ai_workshop.labs.rag.executions.observer import ExecutionObserver


class Recorder:
    def __init__(self, broken=False):
        self.rows = []
        self.broken = broken

    async def start(self, identity):
        if self.broken:
            raise RuntimeError("private provider body must never be logged")

    async def record(self, id, observation):
        self.rows.append(observation)

    async def finish(self, id, outcome):
        self.outcome = outcome


@pytest.mark.asyncio
async def test_failure_records_active_stage_and_skips_following():
    recorder = Recorder()
    observer = ExecutionObserver(ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), recorder)
    await observer.start()
    await observer.begin("retrieval")
    await observer.fail("evidence_embedding_unavailable")
    await observer.finish(
        ExecutionOutcome(state="failed", error_code="evidence_embedding_unavailable")
    )
    assert next(row for row in recorder.rows if row.state == "failed").stage == "retrieval"
    assert any(row.stage == "generation" and row.state == "skipped" for row in recorder.rows)


@pytest.mark.asyncio
async def test_recorder_failure_is_incomplete_and_body_not_logged(caplog):
    observer = ExecutionObserver(
        ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), Recorder(True)
    )
    await observer.start()
    assert not observer.complete
    assert observer.persisted_id is None
    assert "private provider body" not in caplog.text


@pytest.mark.asyncio
async def test_selection_metadata_failure_does_not_break_answer():
    from ai_workshop.labs.rag.executions import observer as trace

    observer = ExecutionObserver(ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), Recorder())
    await observer.start()

    def invalid():
        raise ValueError("private body")

    token = trace.current_observer.set(observer)
    try:
        await trace.capture_selection(invalid)
        assert not observer.complete
    finally:
        trace.current_observer.reset(token)
