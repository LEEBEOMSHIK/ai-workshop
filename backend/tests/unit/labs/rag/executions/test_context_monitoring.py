"""Offline regression for original message identity and separate HTTP context capture."""

import json
from uuid import uuid4

import httpx
import pytest

from ai_workshop.labs.rag.executions.agent_trace import (
    AgentTraceCollector,
    capture_agent_trace,
    current_agent_trace,
)
from ai_workshop.labs.rag.executions.domain import ExecutionIdentity
from ai_workshop.labs.rag.executions.observer import ExecutionObserver, observed_call
from ai_workshop.labs.rag.generation.domain import (
    ContextPolicy,
    ContextualizationRequest,
    ConversationRole,
    ConversationTurn,
)
from ai_workshop.labs.rag.generation.openai_compatible import LocalOpenAICompatibleRuntime
from tests.unit.labs.rag.executions.test_observer import Recorder
from tests.unit.labs.rag.generation.test_openai_compatible import client_for
from tests.unit.labs.rag.orchestration.test_agents_sdk import request


def test_history_records_positions_not_text_or_public_message_ids():
    from ai_workshop.labs.rag.executions.history_selection import (
        bind_history_provenance,
        history_selection,
    )

    ids = (uuid4(), uuid4(), uuid4())
    history = tuple(ConversationTurn(
        role=ConversationRole.USER if i % 2 == 0 else ConversationRole.ASSISTANT,
        content="same text", turn_id=uuid4(), validation_token="signed" if i % 2 else None,
    ) for i in range(6))
    policy = ContextPolicy(5, 3)
    calls = []

    def count(text):
        calls.append(text)
        return 2

    with bind_history_provenance(ids):
        selected = policy.select(history, token_counter=count)
        observed = history_selection(history, selected, policy)
    assert selected == (history[-1],)
    assert calls == ["same text", "same text"]
    assert [m.conversation_turn_id for m in observed.messages] == [
        id for id in ids for _ in range(2)
    ]
    assert [m.position for m in observed.messages] == list(range(6))
    assert [m.reason for m in observed.messages] == [
        "message_limit", "older_than_token_limit", "older_than_token_limit",
        "older_than_token_limit", "token_limit", "selected",
    ]
    assert observed.selected_message_count == 1
    assert "same text" not in observed.model_dump_json()
    assert all(m.conversation_turn_id is None for m in
               history_selection(history, selected, policy).messages)
    with bind_history_provenance(ids[:1]):
        assert all(m.conversation_turn_id is None for m in
                   history_selection(history, selected, policy).messages)


@pytest.mark.parametrize("invalid", [False, True])
async def test_context_http_capture_is_exact_separate_and_rejects_unsafe_output(invalid):
    from ai_workshop.labs.rag.executions.contextualization import current_contextualization

    calls = []

    def handler(value):
        calls.append(json.loads(value.content))
        return httpx.Response(200, json={"model": profile.runtime_model, "choices": [{
            "index": 0, "finish_reason": "stop", "message": {
                "role": "assistant", "content": '{"resolved_query":"synthetic query"}',
                **({"reasoning_content": "PRIVATE_REASONING_CANARY"} if invalid else {}),
            },
        }]})

    profile = request().profile
    runtime = LocalOpenAICompatibleRuntime(
        deployment=profile.deployment, endpoint="http://127.0.0.1:11434", dialect="ollama",
        client=client_for(httpx.MockTransport(handler)),
    )
    recorder = Recorder()
    observer = ExecutionObserver(ExecutionIdentity(actor_id=uuid4(), turn_id=uuid4()), recorder)

    async def run():
        with capture_agent_trace(True):
            await observer.begin("contextualization")
            try:
                await runtime.contextualize(ContextualizationRequest(
                    question="synthetic question", history=(), profile=profile,
                ))
            except Exception:
                if not invalid:
                    raise
            captured = current_contextualization()
            assert captured is not None
            assert json.loads(captured.input.text) == {
                key: value for key, value in calls[0].items() if key != "model"
            }
            assert captured.instructions.text == calls[0]["messages"][0]["content"]
            assert "PRIVATE_REASONING_CANARY" not in captured.model_dump_json()
            assert (captured.output.text is None) is invalid
            assert captured.observation_complete is not invalid
            if invalid:
                assert captured.output.content_status == "not_applicable"
            assert current_agent_trace() is None
            await observer.end("contextualization")
            assert recorder.rows[-1].contextualization == captured
    await observed_call(run(), observer)
    await runtime.client.aclose()


async def test_context_and_sdk_share_total_content_limit():
    from ai_workshop.labs.rag.executions.contextualization import record_contextualization_input

    with capture_agent_trace(True):
        record_contextualization_input({"messages": [{"role": "system", "content": "x" * 30000}]})
        collector = AgentTraceCollector()
        root = await collector.start_span(kind="agent", name="answer", input="y" * 30000)
        await collector.start_span(kind="model", name="model", parent_id=root, input="z" * 30000)
        await collector.end_span(root, output="q" * 30000)
        trace = current_agent_trace()
        assert trace.spans[0].output.content_status == "omitted_size_limit"
        assert trace.truncated and not trace.observation_complete


async def test_inherited_observer_retains_sdk_content_with_diagnostics_false():
    from tests.unit.labs.rag.orchestration.test_agents_sdk import response, runner
    from tests.unit.labs.rag.orchestration.test_pipeline import ACTOR_ID, query, service

    class TraceRecorder(Recorder):
        async def record_agent_trace(self, execution_id, trace):
            self.trace = trace

    recorder = TraceRecorder()
    observer = ExecutionObserver(ExecutionIdentity(actor_id=ACTOR_ID, turn_id=uuid4()), recorder)
    target, _, _ = service(dispatch_mode="direct_answer")
    target.generation_orchestrator = runner(lambda value: response(value, content={
        "schema_version": 2, "status": "insufficient_evidence", "claims": [],
    }))
    result = await observed_call(target.search(
        actor_id=ACTOR_ID, request=query().model_copy(update={"include_diagnostics": False}),
    ), observer)
    assert result.diagnostics is None
    assert recorder.trace.spans[0].input.content_status == "complete"


@pytest.mark.parametrize("content", [
    "not json",
    '{"resolved_query":"one","resolved_query":"two"}',
    '{"resolved_query":"synthetic query","reasoning":"PRIVATE_CANARY"}',
    '{"resolved_query":""}',
])
async def test_invalid_context_contract_never_retains_raw_output_or_digest(content):
    from ai_workshop.labs.rag.executions.contextualization import current_contextualization
    from ai_workshop.labs.rag.generation.execution import GenerationProviderError

    profile = request().profile
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={
        "model": profile.runtime_model, "choices": [{"index": 0, "finish_reason": "stop",
        "message": {"role": "assistant", "content": content}}],
    }))
    async with client_for(transport) as client:
        runtime = LocalOpenAICompatibleRuntime(
            deployment=profile.deployment, endpoint="http://127.0.0.1:11434",
            dialect="ollama", client=client,
        )
        with capture_agent_trace(True):
            with pytest.raises(GenerationProviderError):
                await runtime.contextualize(ContextualizationRequest(
                    question="synthetic question", history=(), profile=profile,
                ))
            captured = current_contextualization()
            assert captured is not None and not captured.observation_complete
            assert captured.output.content_status == "not_applicable"
            assert captured.output.text is captured.output.sha256 is None
            assert "PRIVATE_CANARY" not in captured.model_dump_json()


async def test_storage_validates_combined_limit_and_preserves_legacy_stage_bytes():
    from ai_workshop.labs.rag.executions.agent_trace import TRACE_STORAGE_KEY
    from ai_workshop.labs.rag.executions.contextualization import (
        current_contextualization,
        record_contextualization_input,
    )
    from ai_workshop.labs.rag.executions.domain import StageObservation
    from ai_workshop.labs.rag.executions.execution_content import storage_stages

    with capture_agent_trace(True):
        record_contextualization_input({"messages": [{"role": "system", "content": "x" * 30000}]})
        context = current_contextualization()
    with capture_agent_trace(True):
        collector = AgentTraceCollector()
        root = await collector.start_span(kind="agent", name="answer", input="y" * 30000)
        await collector.start_span(kind="model", name="model", parent_id=root, input="z" * 30000)
        await collector.end_span(root, output="q" * 30000)
        trace = current_agent_trace()
    stages = {"retrieval": {"stage": "retrieval", "state": "completed"}}
    assert storage_stages(stages) == stages
    context_stage = StageObservation(stage="contextualization", state="completed",
                                     contextualization=context).model_dump(mode="json")
    with pytest.raises(ValueError, match="Combined"):
        storage_stages({"contextualization": context_stage,
                        TRACE_STORAGE_KEY: trace.model_dump(mode="json")})
    context_stage["contextualization"].pop("content_retention")
    legacy = storage_stages({"contextualization": context_stage})
    assert legacy["contextualization"]["contextualization"]["input"]["text"] is None


def test_source_binding_requires_exact_order_and_unknown_ids_cannot_claim_a_turn():
    from ai_workshop.labs.rag.executions.history_selection import (
        bind_history_provenance,
        history_selection,
        validate_history_binding,
    )

    ids = (uuid4(), uuid4())
    turns = tuple(ConversationTurn(
        role=ConversationRole.USER if i % 2 == 0 else ConversationRole.ASSISTANT,
        content="same text", validation_token="signed" if i % 2 else None,
    ) for i in range(4))
    policy = ContextPolicy(4, 10)
    with bind_history_provenance(ids):
        value = history_selection(turns, turns, policy)
    validate_history_binding(value, ids)
    with pytest.raises(ValueError, match="dependencies"):
        validate_history_binding(value, tuple(reversed(ids)))
    with pytest.raises(ValueError, match="dependencies"):
        validate_history_binding(value, ())
