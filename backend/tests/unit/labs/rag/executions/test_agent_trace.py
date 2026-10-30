from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.executions.agent_trace import (
    AgentTrace,
    AgentTraceCollector,
    capture_agent_trace,
    current_agent_trace,
    next_agent_trace,
    persisted_agent_trace,
    response_agent_trace,
)


async def test_trace_retains_actual_parent_and_body_but_metadata_projection_omits_it():
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        root = await collector.start_span(kind="agent", name="manager", input="synthetic question")
        child = await collector.start_span(
            kind="delegation", name="answer", parent_id=root,
            from_agent="manager", to_agent="answer", delegation_mode="as_tool",
            input="Explain the payment rule from the supplied evidence.",
        )
        await collector.end_span(
            child, output="synthetic answer", input_tokens=None, output_tokens=0,
        )
        await collector.end_span(root, output="synthetic answer")
        trace = current_agent_trace()
        assert trace is not None
        assert trace.spans[1].parent_id == root
        assert trace.spans[1].input.text == "Explain the payment rule from the supplied evidence."
        assert trace.spans[1].input_tokens is None
        assert trace.spans[1].output_tokens == 0
        stored = persisted_agent_trace(trace)
        assert "synthetic" not in stored.model_dump_json()
        assert stored.spans[1].input.content_status == "not_retained"
        assert stored.spans[1].input.sha256 == trace.spans[1].input.sha256
        assert stored.revision == 4
    assert current_agent_trace() is None


async def test_capture_disabled_and_size_limit_never_return_partial_bodies():
    with capture_agent_trace(False):
        collector = AgentTraceCollector()
        await collector.start_span(kind="agent", name="manager", input="private synthetic")
        trace = current_agent_trace()
        assert trace is not None and trace.spans[0].input.text is None
        assert trace.spans[0].input.content_status == "disabled"
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        await collector.start_span(kind="agent", name="manager", input="x" * 32769)
        trace = current_agent_trace()
        assert trace is not None and trace.spans[0].input.text is None
        assert trace.spans[0].input.content_status == "omitted_size_limit"
        assert trace.spans[0].input.characters == 32769


async def test_late_end_cannot_rewrite_terminal_span_and_identity_is_server_owned():
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        root = await collector.start_span(kind="agent", name="manager")
        await collector.end_span(root, state="cancelled", error_code="cancelled")
        await collector.end_span(root, output="late answer")
        trace = current_agent_trace()
        assert trace is not None and trace.spans[0].state == "cancelled"
        assert trace.revision == 2
        assert trace.spans[0].output.text is None
        invalid = trace.model_dump()
        invalid["spans"][0]["parent_id"] = uuid4()
        with pytest.raises(ValidationError):
            AgentTrace.model_validate(invalid)


async def test_limit_marks_observation_incomplete_without_crashing_generation():
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        root = await collector.start_span(kind="agent", name="manager")
        for _ in range(70):
            await collector.start_span(kind="tool", name="answer", parent_id=root)
        trace = current_agent_trace()
        assert trace is not None
        assert len(trace.spans) == 64
        assert trace.truncated and not trace.observation_complete


async def test_snapshot_revision_rejects_other_run_regression_and_terminal_changes():
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        root = await collector.start_span(kind="agent", name="manager", input="synthetic only")
        first = current_agent_trace()
        assert first is not None
        stored = next_agent_trace(None, first)
        assert stored is not None and stored["spans"][0]["input"]["text"] == "synthetic only"
        assert next_agent_trace(stored, first) is None
        with pytest.raises(ValueError, match="identity"):
            next_agent_trace(stored, first.model_copy(update={"run_id": uuid4(), "revision": 99}))
        await collector.end_span(root)
        last = current_agent_trace()
        assert last is not None
        ended = next_agent_trace(stored, last)
        assert ended is not None
        with pytest.raises(ValueError, match="Terminal"):
            next_agent_trace(ended, first.model_copy(update={"revision": 100}))


async def test_observer_failures_are_incomplete_and_do_not_log_raw_content(caplog):
    from ai_workshop.labs.rag.executions.domain import ExecutionIdentity
    from ai_workshop.labs.rag.executions.observer import ExecutionObserver, observed_call
    from tests.unit.labs.rag.executions.test_observer import Recorder

    class BrokenRecorder(Recorder):
        async def record_agent_trace(self, execution_id, trace):
            assert trace.spans[0].input.text == "synthetic secret marker"
            raise ValueError("synthetic secret marker")

    observer = ExecutionObserver(
        ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), BrokenRecorder(),
    )

    async def run():
        with capture_agent_trace(True):
            collector = AgentTraceCollector()
            await collector.start_span(
                kind="agent", name="manager", input="synthetic secret marker",
            )
            value = current_agent_trace()
            assert value is not None and not value.observation_complete
            return "answer"

    assert await observed_call(run(), observer) == "answer"
    assert not observer.complete
    assert "synthetic secret marker" not in caplog.text


async def test_invalid_answer_draft_is_not_reintroduced_through_trace_outputs():
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        root = await collector.start_span(kind="agent", name="manager", input="authorized input")
        await collector.end_span(root, output="unvalidated synthetic draft")
        valid = response_agent_trace(answer_validated=True)
        invalid = response_agent_trace(answer_validated=False)
        assert valid is not None and "unvalidated synthetic draft" in valid.model_dump_json()
        assert invalid is not None
        assert "unvalidated synthetic draft" not in invalid.model_dump_json()
        assert invalid.spans[0].input.text == "authorized input"
        assert invalid.spans[0].output.content_status == "omitted_validation_failure"
        assert invalid.spans[0].output.sha256 == valid.spans[0].output.sha256
