"""Independent timing, task-isolation and data-minimization contract checks."""

import asyncio
import inspect
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.executions import operation_timings
from ai_workshop.labs.rag.executions.domain import (
    ExecutionIdentity,
    ExecutionOutcome,
    OperationTiming,
    StageObservation,
)
from ai_workshop.labs.rag.executions.observer import (
    ExecutionObserver,
    current_observer,
    observed_call,
)
from ai_workshop.labs.rag.executions.operation_timings import measure_operation


class RecordingSink:
    def __init__(self) -> None:
        self.rows: list[StageObservation] = []
        self.outcomes: list[ExecutionOutcome] = []

    async def start(self, identity: ExecutionIdentity) -> None:
        pass

    async def record(self, execution_id: UUID, observation: StageObservation) -> None:
        self.rows.append(observation.model_copy(deep=True))

    async def finish(self, execution_id: UUID, outcome: ExecutionOutcome) -> None:
        self.outcomes.append(outcome.model_copy(deep=True))


def _observer() -> tuple[ExecutionObserver, RecordingSink]:
    sink = RecordingSink()
    observer = ExecutionObserver(ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), sink)
    return observer, sink


def _completed(sink: RecordingSink, stage: str) -> StageObservation:
    return next(row for row in reversed(sink.rows) if row.stage == stage and row.state != "running")


class Clock:
    value = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


async def test_nested_spans_are_inclusive_and_repeat_calls_accumulate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = Clock()
    monkeypatch.setattr(operation_timings, "perf_counter", clock)
    observer, sink = _observer()
    await observer.start()
    await observer.begin("retrieval")

    async def work() -> None:
        with measure_operation("retrieval.bm25", items=2):
            clock.advance(0.003)
            with measure_operation("keyword.normalize", items=3, reused_items=1):
                clock.advance(0.007)
            clock.advance(0.001)
        with measure_operation("retrieval.bm25", items=1):
            clock.advance(0.005)

    await observed_call(work(), observer)
    await observer.end("retrieval")
    rows = _completed(sink, "retrieval").operations
    assert rows is not None
    operations = {row.name: row for row in rows}
    assert set(operations) == {"retrieval.bm25", "keyword.normalize"}
    outer = operations["retrieval.bm25"]
    inner = operations["keyword.normalize"]
    assert outer.duration_ms == pytest.approx(16.0)
    assert (outer.calls, outer.failures, outer.items, outer.reused_items) == (2, 0, 3, 0)
    assert inner.duration_ms == pytest.approx(7.0)
    assert (inner.calls, inner.items, inner.reused_items) == (1, 3, 1)


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_failure_and_cancellation_propagate_without_retaining_messages(
    failure: type[BaseException], caplog: pytest.LogCaptureFixture,
) -> None:
    observer, sink = _observer()
    await observer.start()
    await observer.begin("retrieval")
    marker = "synthetic_private_exception_marker_765"
    error = failure(marker)

    async def work() -> None:
        with measure_operation("retrieval.sources", items=4):
            raise error

    with pytest.raises(failure) as raised:
        await observed_call(work(), observer)
    assert raised.value is error
    assert current_observer.get() is None
    await observer.end("retrieval", state="failed", reason="synthetic_failure")
    rows = _completed(sink, "retrieval").operations
    assert rows is not None and len(rows) == 1
    assert (rows[0].calls, rows[0].failures, rows[0].items) == (1, 1, 4)
    assert marker not in _completed(sink, "retrieval").model_dump_json()
    assert marker not in caplog.text


async def test_concurrent_observers_never_exchange_operation_counts() -> None:
    first, first_sink = _observer()
    second, second_sink = _observer()
    ready = [asyncio.Event(), asyncio.Event()]
    release = asyncio.Event()

    async def work(observer: ExecutionObserver, index: int, items: int) -> None:
        await observer.start()
        await observer.begin("retrieval")
        with measure_operation("retrieval.dense", items=items):
            ready[index].set()
            await release.wait()
        await observer.end("retrieval")

    tasks = [
        asyncio.create_task(observed_call(work(first, 0, 2), first)),
        asyncio.create_task(observed_call(work(second, 1, 7), second)),
    ]
    await asyncio.gather(*(event.wait() for event in ready))
    release.set()
    await asyncio.gather(*tasks)
    for sink, expected_items in ((first_sink, 2), (second_sink, 7)):
        rows = _completed(sink, "retrieval").operations
        assert rows is not None and len(rows) == 1
        assert rows[0].name == "retrieval.dense"
        assert (rows[0].calls, rows[0].items) == (1, expected_items)
    assert current_observer.get() is None


async def test_late_child_completion_cannot_move_to_next_stage_or_change_saved_stage() -> None:
    observer, sink = _observer()
    ready, release = asyncio.Event(), asyncio.Event()

    async def child() -> None:
        with measure_operation("retrieval.bm25", items=5):
            ready.set()
            await release.wait()

    async def parent() -> None:
        await observer.start()
        await observer.begin("retrieval")
        task = asyncio.create_task(child())
        await ready.wait()
        await observer.end("retrieval")
        saved = _completed(sink, "retrieval").model_dump_json()
        await observer.begin("selection")
        release.set()
        await task
        await observer.end("selection")
        assert _completed(sink, "retrieval").model_dump_json() == saved
        assert _completed(sink, "retrieval").operations == []
        assert _completed(sink, "selection").operations == []

    await observed_call(parent(), observer)


async def test_finished_execution_rejects_scope_completion_without_extra_record_writes() -> None:
    observer, sink = _observer()

    async def work() -> None:
        await observer.start()
        await observer.begin("selection")
        with measure_operation("selection.context", items=2):
            await observer.finish(ExecutionOutcome(state="cancelled"))
            snapshot = [row.model_dump_json() for row in sink.rows]
        assert [row.model_dump_json() for row in sink.rows] == snapshot
        assert len(sink.outcomes) == 1
        assert all(not row.operations for row in sink.rows)

    await observed_call(work(), observer)


async def test_cancelled_stage_write_remains_available_to_the_cancellation_finalizer() -> None:
    entered_write = asyncio.Event()

    class InterruptedSink(RecordingSink):
        async def record(self, execution_id: UUID, observation: StageObservation) -> None:
            if observation.stage == "retrieval" and observation.state == "completed":
                entered_write.set()
                await asyncio.Event().wait()
            await super().record(execution_id, observation)

    sink = InterruptedSink()
    observer = ExecutionObserver(ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), sink)
    await observer.start()
    await observer.begin("retrieval")
    completing = asyncio.create_task(observer.end("retrieval"))
    await entered_write.wait()
    completing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await completing

    # This is the existing conversation finalizer's sequence after cancellation.
    await observer.fail("conversation_cancelled")
    await observer.finish(ExecutionOutcome(state="cancelled"))
    assert any(
        row.stage == "retrieval" and row.state == "failed"
        and row.reason == "conversation_cancelled"
        for row in sink.rows
    ), "Interrupted persistence must not mark the stage as durably completed"
    assert sink.outcomes[-1].state == "cancelled"


def test_absent_observer_does_not_read_the_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden() -> float:
        raise AssertionError("No observer must be a no-op")

    monkeypatch.setattr(operation_timings, "perf_counter", forbidden)
    assert current_observer.get() is None
    with measure_operation("keyword.normalize", items=1):
        result = "synthetic result"
    assert result == "synthetic result"


async def test_broken_clock_does_not_replace_business_result_or_log_body(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    observer, sink = _observer()
    await observer.start()
    await observer.begin("selection")

    def broken() -> float:
        raise RuntimeError("synthetic_clock_private_marker")

    monkeypatch.setattr(operation_timings, "perf_counter", broken)

    async def work() -> str:
        with measure_operation("keyword.normalize", items=1):
            return "unchanged result"

    assert await observed_call(work(), observer) == "unchanged result"
    assert not observer.complete
    assert "synthetic_clock_private_marker" not in caplog.text
    await observer.end("selection")
    assert not _completed(sink, "selection").operations


@pytest.mark.parametrize(
    "override",
    [
        {"name": "document.private_title"},
        {"duration_ms": -0.1},
        {"duration_ms": float("inf")},
        {"duration_ms": float("nan")},
        {"calls": 0},
        {"calls": 1.5},
        {"failures": -1},
        {"failures": 2},
        {"items": -1},
        {"reused_items": -1},
        {"reused_items": 2},
        {"text": "synthetic private body"},
        {"query": "synthetic private question"},
        {"exception": "synthetic private failure"},
        {"endpoint": "https://synthetic.invalid/"},
        {"document_id": str(UUID(int=44))},
    ],
)
def test_operation_schema_rejects_unapproved_metadata(override: dict[str, object]) -> None:
    baseline: dict[str, object] = dict(
        name="keyword.normalize", duration_ms=0.0, calls=1, failures=0, items=1, reused_items=0,
    )
    with pytest.raises(ValidationError):
        OperationTiming.model_validate({**baseline, **override})


def test_stage_rejects_duplicate_names_and_excessive_operation_lists() -> None:
    operation = dict(
        name="keyword.normalize", duration_ms=1.0, calls=1, failures=0, items=0, reused_items=0,
    )
    for count in (2, 17):
        with pytest.raises(ValidationError):
            StageObservation.model_validate(dict(
                stage="selection", state="completed", operations=[operation] * count,
            ))


def test_old_json_and_observed_empty_list_have_different_meanings() -> None:
    legacy = StageObservation.model_validate_json('{"stage":"selection","state":"completed"}')
    observed = StageObservation(stage="selection", state="completed", operations=[])
    assert legacy.operations is None
    assert observed.operations == []
    assert "operations" not in legacy.model_dump(mode="json")
    assert observed.model_dump(mode="json")["operations"] == []


def test_measurement_api_has_no_freeform_metadata_slot() -> None:
    parameters = inspect.signature(measure_operation).parameters
    assert set(parameters) == {"name", "items", "reused_items"}
    assert all(parameter.kind != inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())
    assert set(OperationTiming.model_fields) == {
        "name", "duration_ms", "calls", "failures", "items", "reused_items",
    }
