import asyncio
import importlib
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.executions import domain
from ai_workshop.labs.rag.executions.observer import (
    ExecutionObserver,
    current_observer,
    observed_call,
)


class Recorder:
    def __init__(self):
        self.rows = []
        self.outcome = None

    async def start(self, identity):
        pass

    async def record(self, execution_id, observation):
        self.rows.append(observation.model_dump(mode="json"))

    async def finish(self, execution_id, outcome):
        self.outcome = outcome


def observer(recorder=None):
    return ExecutionObserver(
        domain.ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), recorder or Recorder()
    )


def timings_module():
    name = "ai_workshop.labs.rag.executions.operation_timings"
    assert importlib.util.find_spec(name) is not None, "operation timing helper is required"
    return importlib.import_module(name)


def operation_model():
    assert hasattr(domain, "OperationTiming"), "closed operation timing contract is required"
    return domain.OperationTiming


def test_old_stage_json_is_unmeasured_and_empty_measurement_is_explicit():
    old = domain.StageObservation.model_validate({"stage": "retrieval", "state": "completed"})
    assert hasattr(old, "operations"), "stage must represent unmeasured operation timings"
    assert old.operations is None
    assert "operations" not in old.model_dump(mode="json")
    measured = domain.StageObservation(stage="retrieval", state="completed", operations=[])
    assert measured.model_dump(mode="json")["operations"] == []


@pytest.mark.parametrize(
    "invalid",
    [
        {"name": "private query"}, {"duration_ms": float("nan")},
        {"duration_ms": float("inf")}, {"duration_ms": -1}, {"calls": 0},
        {"calls": True}, {"calls": 1.5}, {"failures": 2}, {"items": -1},
        {"reused_items": 3}, {"query": "private query"}, {"endpoint": "private endpoint"},
    ],
)
def test_operation_contract_rejects_unbounded_or_non_numeric_metadata(invalid):
    values = dict(
        name="embedding.query", duration_ms=1.25, calls=1, failures=0, items=2, reused_items=1
    )
    values.update(invalid)
    with pytest.raises(ValidationError):
        operation_model().model_validate(values)


def test_stage_rejects_duplicate_operations_and_overlong_list():
    entry = operation_model()(
        name="embedding.query", duration_ms=0, calls=1, failures=0, items=0, reused_items=0
    )
    for entries in ([entry, entry], [entry] * 17):
        with pytest.raises(ValidationError):
            domain.StageObservation(stage="retrieval", state="completed", operations=entries)


@pytest.mark.asyncio
async def test_inclusive_nested_calls_aggregate_without_additional_recorder_writes(monkeypatch):
    timings = timings_module()
    times = iter([0.0, 0.1, 0.3, 0.5, 1.0, 1.25])
    monkeypatch.setattr(timings, "perf_counter", lambda: next(times))
    item = observer()

    async def run():
        await item.begin("selection")
        with (
            timings.measure_operation("selection.extractive", items=3),
            timings.measure_operation("embedding.documents", items=2),
        ):
            pass
        with timings.measure_operation("embedding.documents", items=3, reused_items=2):
            pass
        await item.end("selection")

    await observed_call(run(), item)
    assert len(item.recorder.rows) == 2
    operations = {row["name"]: row for row in item.recorder.rows[-1]["operations"]}
    assert operations["selection.extractive"] == dict(
        name="selection.extractive", duration_ms=500, calls=1, failures=0, items=3, reused_items=0
    )
    documents = operations["embedding.documents"]
    assert documents["duration_ms"] == pytest.approx(450)
    assert documents == dict(
        name="embedding.documents", duration_ms=pytest.approx(450), calls=2,
        failures=0, items=5, reused_items=2,
    )
    assert current_observer.get() is None


@pytest.mark.asyncio
async def test_failed_and_cancelled_body_propagate_and_remain_body_free():
    timings = timings_module()
    item = observer()

    async def run():
        await item.begin("retrieval")
        for error in (ValueError("private body"), asyncio.CancelledError("private cancellation")):
            with (
                pytest.raises(type(error)) as caught,
                timings.measure_operation("retrieval.bm25"),
            ):
                raise error
            assert caught.value is error
        await item.end("retrieval", state="failed")

    await observed_call(run(), item)
    operation = item.recorder.rows[-1]["operations"][0]
    assert operation["calls"] == operation["failures"] == 2
    assert "private" not in str(item.recorder.rows)


@pytest.mark.asyncio
async def test_parallel_requests_are_isolated_and_nested_context_is_restored():
    timings = timings_module()
    first, second = observer(), observer()
    ready, release = asyncio.Event(), asyncio.Event()

    async def run(item, name):
        await item.begin("retrieval")
        with timings.measure_operation(name):
            ready.set()
            await release.wait()
        await item.end("retrieval")

    token = current_observer.set(first)
    try:
        tasks = [
            asyncio.create_task(observed_call(run(first, "retrieval.bm25"), first)),
            asyncio.create_task(observed_call(run(second, "retrieval.dense"), second)),
        ]
        await ready.wait()
        release.set()
        await asyncio.gather(*tasks)
        assert current_observer.get() is first
    finally:
        current_observer.reset(token)
    assert [row["name"] for row in first.recorder.rows[-1]["operations"]] == ["retrieval.bm25"]
    assert [row["name"] for row in second.recorder.rows[-1]["operations"]] == ["retrieval.dense"]


@pytest.mark.asyncio
async def test_late_scope_cannot_modify_a_saved_or_restarted_stage():
    timings = timings_module()
    item = observer()

    async def run():
        await item.begin("retrieval")
        with timings.measure_operation("retrieval.bm25"):
            await item.end("retrieval")
            await item.begin("retrieval")
        with timings.measure_operation("retrieval.dense"):
            pass
        await item.end("retrieval")
        await item.finish(domain.ExecutionOutcome(state="completed"))
        with timings.measure_operation("retrieval.sources"):
            pass

    await observed_call(run(), item)
    rows = [row for row in item.recorder.rows if row["stage"] == "retrieval"]
    assert rows[1]["operations"] == []
    assert [row["name"] for row in rows[3]["operations"]] == ["retrieval.dense"]
    assert item.recorder.outcome.complete is True


def test_absent_observer_is_noop_even_when_clock_is_broken(monkeypatch):
    timings = timings_module()

    def broken():
        raise RuntimeError("private timing error")

    monkeypatch.setattr(timings, "perf_counter", broken)
    with timings.measure_operation("retrieval.bm25"):
        result = 42
    assert result == 42


@pytest.mark.asyncio
async def test_invalid_measurement_is_non_disruptive_but_marks_observation_incomplete(caplog):
    timings = timings_module()
    item = observer()

    async def run():
        await item.begin("retrieval")
        with timings.measure_operation("private body", items=-1):
            result = 42
        await item.end("retrieval")
        await item.finish(domain.ExecutionOutcome(state="completed"))
        return result

    assert await observed_call(run(), item) == 42
    assert item.recorder.outcome.complete is False
    assert "private body" not in str(item.recorder.rows) + caplog.text
