"""Private step bodies survive only the execution boundary, using synthetic inputs."""

import hashlib
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.executions.agent_trace import (
    TRACE_STORAGE_KEY,
    AgentTraceCollector,
    capture_agent_trace,
    current_agent_trace,
    next_agent_trace,
    persisted_agent_trace,
    read_agent_trace,
    response_agent_trace,
)
from ai_workshop.labs.rag.executions.domain import ExecutionIdentity
from ai_workshop.labs.rag.executions.observer import ExecutionObserver, observed_call
from ai_workshop.labs.rag.search.pipeline import PipelineInput
from ai_workshop.labs.rag.search.schemas import SearchDiagnosticsResponse
from tests.unit.labs.rag.conversations.test_service import seed_conversation
from tests.unit.labs.rag.conversations.test_service import setup as conversation_setup  # noqa: F401
from tests.unit.labs.rag.executions.test_observer import Recorder
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, request, response, runner
from tests.unit.labs.rag.orchestration.test_pipeline import query, service
from tests.unit.labs.rag.search.test_generation_policy_gate import ACTOR_ID


class TraceRecorder(Recorder):
    def __init__(self):
        super().__init__()
        self.stored = None

    async def record_agent_trace(self, execution_id, trace):
        value = next_agent_trace(self.stored, trace)
        if value is not None:
            self.stored = value


async def completed_trace():
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        span = await collector.start_span(
            kind="agent", name="manager", instructions="합성 지침", input="합성 질문 😀",
        )
        await collector.end_span(span, output="")
        return current_agent_trace()


async def test_retained_storage_preserves_unicode_and_empty_output_but_metadata_does_not():
    trace = await completed_trace()
    stored = next_agent_trace(None, trace)
    restored = read_agent_trace({TRACE_STORAGE_KEY: stored})
    assert restored.spans[0].input.text == "합성 질문 😀"
    assert restored.spans[0].output.text == ""
    assert restored.spans[0].input.characters == 7
    assert restored.spans[0].input.sha256 == hashlib.sha256("합성 질문 😀".encode()).hexdigest()
    assert restored.content_retention == "retained"
    projected = persisted_agent_trace(restored)
    assert projected.content_retention == "metadata_only"
    assert all(getattr(projected.spans[0], field).text is None
               for field in ("instructions", "input", "output"))


async def test_legacy_body_is_not_promoted_and_new_absent_fields_are_not_applicable():
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        await collector.start_span(kind="agent", name="manager", input="synthetic")
        trace = current_agent_trace()
    assert trace.spans[0].instructions.content_status == "not_applicable"
    legacy = trace.model_dump(mode="json")
    legacy.pop("content_retention", None)
    restored = read_agent_trace({TRACE_STORAGE_KEY: legacy})
    assert restored.content_retention == "metadata_only"
    assert restored.spans[0].input.text is None
    assert restored.spans[0].input.content_status == "not_retained"


@pytest.mark.parametrize("field,value", [("characters", 99), ("sha256", "0" * 64)])
async def test_storage_revalidates_model_copy_content_integrity(field, value):
    trace = await completed_trace()
    content = trace.spans[0].input.model_copy(update={field: value})
    span = trace.spans[0].model_copy(update={"input": content})
    forged = trace.model_copy(update={"spans": (span,)})
    with pytest.raises(ValidationError):
        next_agent_trace(None, forged)


async def test_total_limit_omits_whole_value_and_marks_observation_incomplete():
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        root = await collector.start_span(kind="agent", name="manager", input="a" * 32768)
        for _ in range(3):
            await collector.start_span(kind="tool", name="answer", parent_id=root,
                                       input="b" * 32768)
        await collector.end_span(root, output="must be omitted")
        trace = current_agent_trace()
    assert trace.spans[0].output.content_status == "omitted_size_limit"
    assert trace.spans[0].output.text is None
    assert trace.truncated and not trace.observation_complete


async def test_real_sdk_records_exact_agent_inputs_and_safe_wire_bodies():
    calls = []

    def handler(value):
        calls.append(json.loads(value.content))
        return response(value, delegate=len(calls) == 1)

    recorder = TraceRecorder()
    observer = ExecutionObserver(ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), recorder)
    with capture_agent_trace(True):
        await observed_call(runner(handler).generate(request(), policy=POLICY), observer)
    trace = read_agent_trace({TRACE_STORAGE_KEY: recorder.stored})
    agents = [span for span in trace.spans if span.kind == "agent"]
    models = [span for span in trace.spans if span.kind == "model"]
    assert len(calls) == len(agents) == len(models) == 2
    for agent, model, call in zip(agents, models, calls, strict=True):
        assert agent.input.text == call["messages"][-1]["content"]
        assert agent.instructions.text == call["messages"][0]["content"]
        assert json.loads(model.input.text)["messages"] == call["messages"]
    assert all(span.instructions.content_status == "not_applicable"
               for span in trace.spans if span.kind != "agent")
    assert "PRIVATE_REASONING_CANARY" not in trace.model_dump_json()
    assert "Authorization" not in trace.model_dump_json()
    assert "127.0.0.1" not in trace.model_dump_json()


@pytest.mark.parametrize("outcome", ["insufficient_evidence", "wrong_citation"])
async def test_pipeline_retains_private_bodies_without_response_diagnostics(outcome):
    calls = []

    def handler(value):
        calls.append(value)
        return response(value, delegate=len(calls) == 1, content={
            "schema_version": 2,
            "status": "insufficient_evidence" if outcome == "insufficient_evidence" else "answered",
            "claims": [] if outcome == "insufficient_evidence" else [{
                "text": "synthetic invalid citation", "evidence_ids": [str(uuid4())],
            }],
        })

    target, _, _ = service()
    target.generation_orchestrator = runner(handler)
    recorder = TraceRecorder()
    observer = ExecutionObserver(ExecutionIdentity(actor_id=ACTOR_ID,
                                                  evaluation_attempt_id=uuid4()), recorder)
    selected_query = query().model_copy(update={"include_diagnostics": False})
    config = await target.configuration_resolver.resolve(selected_query.configuration_id, ACTOR_ID)
    operation = target.execute(PipelineInput(ACTOR_ID, selected_query, config), observer=observer)
    if outcome == "wrong_citation":
        from ai_workshop.shared.errors import AppError

        with pytest.raises(AppError, match="citation"):
            await operation
    else:
        result = await operation
        assert result.diagnostics is None
    restored = read_agent_trace({TRACE_STORAGE_KEY: recorder.stored})
    assert len(calls) == 2
    assert restored.spans[0].instructions.text
    assert all(span.input.text for span in restored.spans)
    assert restored.spans[-1].output.text


async def test_private_failed_output_does_not_reenter_current_response():
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        span = await collector.start_span(kind="agent", name="manager", input="synthetic")
        await collector.end_span(span, output="synthetic unvalidated result")
        trace = current_agent_trace()
        stored = next_agent_trace(None, trace)
        response_trace = response_agent_trace(answer_validated=False)
    assert read_agent_trace({TRACE_STORAGE_KEY: stored}).spans[0].output.text
    assert response_trace.spans[0].output.content_status == "omitted_validation_failure"
    assert response_trace.spans[0].output.text is None


@pytest.mark.parametrize("legacy", [False, True])
async def test_conversation_history_never_exposes_accidentally_duplicated_bodies(
    conversation_setup, legacy,  # noqa: F811
):
    target, repository, _, executor, actor, incoming = conversation_setup
    created = await seed_conversation(target, "domain", actor)
    trace = await completed_trace()
    executor.execute.return_value.diagnostics = SearchDiagnosticsResponse(
        candidates=[], stages_ms={}, min_keyword_coverage=0.0, min_semantic_score=0.0,
        agent_trace=trace,
    )
    await target.submit("domain", actor, created.id, incoming)
    stored = repository.items[created.id].turns[0].response
    duplicated = trace.model_dump(mode="json")
    if legacy:
        duplicated.pop("content_retention")
    stored["diagnostics"]["agent_trace"] = duplicated
    restored = await target.detail("domain", actor, created.id)
    history_trace = restored.turns[0].response.diagnostics.agent_trace
    assert history_trace.spans[0].input.text is None
    assert history_trace.content_retention == "metadata_only"
    assert stored["diagnostics"]["agent_trace"]["spans"][0]["input"]["text"] == "합성 질문 😀"
