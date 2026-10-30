import asyncio
import json
import logging
import re
from dataclasses import replace
from uuid import UUID

import httpx2
import pytest
from agents import set_trace_processors
from agents.tracing import TracingProcessor

from ai_workshop.labs.rag.executions.agent_trace import (
    capture_agent_trace,
    current_agent_trace,
)
from ai_workshop.labs.rag.generation.domain import GenerationRequest, GenerationStatus
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    GenerationTermination,
    tracked_generation_call,
)
from ai_workshop.labs.rag.generation.runtime_resolver import (
    GenerationRuntimeResolver,
    builtin_generation_runtime_factories,
)
from ai_workshop.labs.rag.models.context_evidence import EvidenceBudget
from ai_workshop.labs.rag.models.orchestration_policy import OrchestrationPolicy
from ai_workshop.labs.rag.orchestration.openai_agents import OpenAIAgentsOrchestrator
from ai_workshop.labs.rag.policies.domain import PolicyDecision
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.generation.test_openai_compatible import evidence, profile
from tests.unit.labs.rag.orchestration.test_policy import configuration


def request(**limits):
    return GenerationRequest(
        question="위험 한도는 얼마인가요?", resolved_query="위험 한도", history=(),
        evidence=(evidence(),), correlation_id=str(UUID(int=29)),
        profile=replace(profile(), response_schema_version=2, prompt_ref="rag-answer-v2",
                        orchestration=OrchestrationPolicy(**configuration(**limits))),
    )


def runner(handler, *, dialect="ollama"):
    resolver = GenerationRuntimeResolver(
        environment="test", endpoint_refs={"local-runtime": "http://127.0.0.1:11434"},
        secret_refs={}, factories=builtin_generation_runtime_factories(
            provider_endpoint_dialects={"local-runtime": dialect},
        ),
    )
    return OpenAIAgentsOrchestrator(
        resolver=resolver, transport_factory=lambda: httpx2.MockTransport(handler),
    )


def answer():
    return {"schema_version": 2, "status": "answered", "claims": [
        {"text": evidence().text, "evidence_ids": [str(evidence().evidence_id)]},
    ]}


def response(http_request, *, delegate=False, content=None, usage=True):
    message = {"role": "assistant", "content": json.dumps(content or answer())}
    if delegate:
        message = {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call_synthetic_1", "type": "function", "function": {
                "name": "write_grounded_answer",
                "arguments": json.dumps({"task": "원질문의 위험 한도와 근거를 설명하세요."}),
            },
        }]}
    message["reasoning"] = "PRIVATE_REASONING_CANARY"
    payload = {"id": "synthetic-chat", "object": "chat.completion", "created": 1,
               "model": profile().runtime_model,
               "choices": [{"index": 0, "message": message,
                            "finish_reason": "tool_calls" if delegate else "stop"}]}
    if usage:
        payload["usage"] = {"prompt_tokens": 30, "completion_tokens": 15, "total_tokens": 45}
    return httpx2.Response(200, json=payload, request=http_request)


POLICY = PolicyDecision(True, None, UUID(int=1), ())


async def test_real_sdk_runner_delegates_and_preserves_source_and_wire_trace():
    calls = []
    authorization_checks = []

    async def authorize():
        authorization_checks.append(True)

    def handler(value):
        assert str(value.url) == "http://127.0.0.1:11434/v1/chat/completions"
        calls.append(json.loads(value.content))
        return response(value, delegate=len(calls) == 1)

    termination = GenerationTermination()
    with capture_agent_trace(True):
        result = await tracked_generation_call(
            runner(handler).generate(request(), policy=POLICY, revalidate=authorize), termination,
        )
        trace = current_agent_trace()
    assert result.status is GenerationStatus.ANSWERED
    assert result.generation.claims[0].text == evidence().text
    assert result.execution.input_tokens == 60
    assert result.execution.output_tokens == 30
    assert termination.confirmed
    assert len(calls) == len(authorization_checks) == 2
    assert calls[0]["tool_choice"] == "required"
    assert calls[0]["parallel_tool_calls"] is False
    assert all(call["model"] == profile().runtime_model for call in calls)
    assert sum(call["max_tokens"] for call in calls) <= 600
    child_input = calls[1]["messages"][-1]["content"]
    assert evidence().text in child_input
    assert request().question in child_input
    assert "원질문의 위험 한도와 근거를 설명하세요." in child_input
    assert calls[1]["response_format"]["type"] == "json_schema"
    assert trace is not None and trace.observation_complete
    assert [span.name for span in trace.spans if span.kind == "agent"] == [
        "rag_manager", "answer_specialist",
    ]
    delegation = next(span for span in trace.spans if span.kind == "delegation")
    child = next(span for span in trace.spans if span.name == "answer_specialist")
    assert child.parent_id == delegation.id
    assert delegation.delegation_mode == "as_tool"
    models = [span for span in trace.spans if span.kind == "model"]
    assert len(models) == 2
    assert all(span.input_kind == "http_request" for span in models)
    assert json.loads(models[1].input.text)["messages"] == calls[1]["messages"]
    serialized = trace.model_dump_json()
    assert "PRIVATE_REASONING_CANARY" not in serialized
    assert "127.0.0.1" not in serialized
    assert "Authorization" not in serialized


async def test_missing_usage_stays_unknown_and_failed_second_call_is_not_retried():
    calls = []

    def handler(value):
        calls.append(value)
        return response(value, delegate=len(calls) == 1, usage=False)

    result = await runner(handler).generate(request(), policy=POLICY)
    assert result.execution.input_tokens is None
    assert result.execution.output_tokens is None
    assert len(calls) == 2


@pytest.mark.parametrize("dialect", ["openai", "ollama"])
@pytest.mark.parametrize("prompt_ref", ["rag-answer-v2", "rag-answer-v4", "rag-answer-v5"])
async def test_korean_instructions_reach_both_models_and_retained_steps(dialect, prompt_ref):
    calls = []

    def handler(value):
        calls.append(json.loads(value.content))
        payload = response(value, delegate=len(calls) == 1).json()
        if dialect == "openai":
            del payload["choices"][0]["message"]["reasoning"]
        return httpx2.Response(200, json=payload, request=value)

    selected = request()
    selected = replace(selected, profile=replace(
        selected.profile, prompt_ref=prompt_ref, evidence_budget=EvidenceBudget(8, 32, 12000),
    ))
    with capture_agent_trace(True):
        result = await runner(handler, dialect=dialect).generate(selected, policy=POLICY)
        trace = current_agent_trace()

    assert result.status is GenerationStatus.ANSWERED
    assert len(calls) == 2
    agents = [span for span in trace.spans if span.kind == "agent"]
    models = [span for span in trace.spans if span.kind == "model"]
    for call, agent, model in zip(calls, agents, models, strict=True):
        instructions = call["messages"][0]["content"]
        assert call["messages"][0]["role"] == "system"
        assert re.search("[가-힣]", instructions)
        # Keep protocol identifiers, but catch an untranslated English prose suffix.
        assert not re.search(r"\b[A-Za-z]+ [A-Za-z]+ [A-Za-z]+\b", instructions)
        assert agent.instructions.text == instructions
        assert json.loads(model.input.text)["messages"] == call["messages"]

    tool = calls[0]["tools"][0]["function"]
    assert tool["name"] == "write_grounded_answer"
    assert re.search("[가-힣]", tool["description"])
    assert set(tool["parameters"]["properties"]) == {"task"}
    child_input = json.loads(calls[1]["messages"][-1]["content"])
    assert child_input["question"] == selected.question
    assert child_input["delegated_task"] == "원질문의 위험 한도와 근거를 설명하세요."
    assert evidence().text in calls[1]["messages"][-1]["content"]
    assert calls[1]["response_format"]["type"] == "json_schema"
    assert result.generation.claims[0].evidence_ids == (evidence().evidence_id,)


@pytest.mark.parametrize("status", [429, 500])
async def test_provider_failure_does_not_retry_or_expose_error_body(status):
    calls = []

    def handler(value):
        calls.append(value)
        return httpx2.Response(status, json={"error": {"message": "PRIVATE_ERROR_CANARY"}},
                              request=value)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError) as caught:
            await runner(handler).generate(request(), policy=POLICY)
        trace = current_agent_trace()
    assert len(calls) == 1
    assert not caught.value.retryable
    assert "PRIVATE_ERROR_CANARY" not in str(caught.value)
    assert "PRIVATE_ERROR_CANARY" not in trace.model_dump_json()
    assert all(span.state == "failed" for span in trace.spans)


async def test_insufficient_run_budget_stops_before_any_model_call():
    calls = []

    def handler(value):
        calls.append(value)
        return response(value, delegate=True)

    with pytest.raises(GenerationProviderError, match="orchestration_budget_exceeded"):
        await runner(handler).generate(request(max_model_calls=1), policy=POLICY)
    assert len(calls) == 0


async def test_deadline_retains_unconfirmed_local_termination():
    entered = asyncio.Event()

    async def handler(value):
        entered.set()
        await asyncio.Event().wait()

    selected = request()
    selected = replace(selected, profile=replace(selected.profile, timeout_seconds=0.05))
    termination = GenerationTermination()
    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError, match="provider_timeout"):
            await tracked_generation_call(
                runner(handler).generate(selected, policy=POLICY), termination,
            )
        trace = current_agent_trace()
    assert entered.is_set()
    assert not termination.confirmed
    assert all(span.state == "failed" for span in trace.spans)


async def test_cancelled_sdk_call_preserves_unconfirmed_termination():
    entered = asyncio.Event()

    async def handler(value):
        entered.set()
        await asyncio.Event().wait()

    termination = GenerationTermination()
    task = asyncio.create_task(tracked_generation_call(
        runner(handler).generate(request(), policy=POLICY), termination,
    ))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not termination.confirmed


async def test_manager_cannot_skip_delegation_and_return_a_fabricated_answer():
    calls = []

    def handler(value):
        calls.append(value)
        return response(value)

    with pytest.raises(GenerationProviderError, match="orchestration_invalid_delegation"):
        await runner(handler).generate(request(), policy=POLICY)
    assert len(calls) == 1


async def test_prior_context_budget_and_deadline_are_preserved_without_calls():
    target = runner(lambda _: pytest.fail("No model call authorized"))
    with pytest.raises(GenerationProviderError, match="orchestration_budget_exceeded"):
        await target.generate(request(), policy=POLICY, prior_model_calls=1,
                              prior_reserved_output_tokens=300)
    with pytest.raises(GenerationProviderError, match="provider_timeout"):
        await target.generate(request(max_model_calls=3, max_total_output_tokens=900),
                              policy=POLICY, prior_model_calls=1,
                              prior_reserved_output_tokens=300, prior_latency_ms=12000)


async def test_current_authorization_is_checked_before_child_model_dispatch():
    calls = []
    checks = []

    def handler(value):
        calls.append(value)
        return response(value, delegate=True)

    async def authorize():
        checks.append(True)
        if len(checks) == 2:
            raise AppError("conversation_scope_changed", "Scope changed", 409)

    with pytest.raises(AppError) as caught:
        await runner(handler).generate(request(), policy=POLICY, revalidate=authorize)
    assert caught.value.code == "conversation_scope_changed"
    assert len(calls) == 1


async def test_trace_export_is_disabled_for_parent_and_nested_agent_and_logs_are_safe(caplog):
    class Processor(TracingProcessor):
        events = []

        def on_trace_start(self, value):
            self.events.append(value)

        def on_trace_end(self, value):
            self.events.append(value)

        def on_span_start(self, value):
            self.events.append(value)

        def on_span_end(self, value):
            self.events.append(value)

        def shutdown(self):
            pass

        def force_flush(self):
            pass

    processor = Processor()
    set_trace_processors([processor])
    calls = []

    def handler(value):
        calls.append(value)
        logging.getLogger("httpcore2.http11").debug("PRIVATE_HEADER_CANARY")
        return response(value, delegate=len(calls) == 1)

    try:
        with caplog.at_level(logging.DEBUG):
            await runner(handler).generate(request(), policy=POLICY)
    finally:
        set_trace_processors([])
    assert len(calls) == 2
    assert processor.events == []
    assert request().question not in caplog.text
    assert evidence().text not in caplog.text
    assert "PRIVATE_REASONING_CANARY" not in caplog.text
    assert "PRIVATE_HEADER_CANARY" not in caplog.text


async def test_missing_projection_identity_is_rejected_before_any_model_call():
    selected = replace(request(), evidence=(replace(evidence(), projection_id=None),))
    with pytest.raises(GenerationProviderError, match="orchestration_not_supported"):
        await runner(lambda _: pytest.fail("No model call authorized")).generate(
            selected, policy=POLICY,
        )


@pytest.mark.parametrize("stage,field,value", [
    (1, "role", "user"), (2, "role", "system"), (2, "reasoning", ["hidden"]),
    (2, "reasoning_content", "unexpected"), (2, "refusal", "unsafe partial answer"),
])
async def test_sdk_preserves_strict_local_message_contract(stage, field, value):
    calls = []

    def handler(http_request):
        calls.append(http_request)
        result = response(http_request, delegate=len(calls) == 1)
        if len(calls) == stage:
            payload = result.json()
            payload["choices"][0]["message"][field] = value
            return httpx2.Response(200, json=payload, request=http_request)
        return result

    with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
        await runner(handler).generate(request(), policy=POLICY)
    assert len(calls) == stage


async def test_duplicate_delegation_keys_are_rejected_without_child_dispatch():
    calls = []

    def handler(http_request):
        calls.append(http_request)
        payload = response(http_request, delegate=True).json()
        payload["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = (
            '{"task":"original","task":"replacement"}'
        )
        return httpx2.Response(200, json=payload, request=http_request)

    with pytest.raises(GenerationProviderError):
        await runner(handler).generate(request(), policy=POLICY)
    assert len(calls) == 1


async def test_reasoning_override_is_not_silently_sent_to_unsupported_dialect():
    selected = request()
    selected = replace(selected, profile=replace(selected.profile, answer_reasoning_effort="none"))
    with pytest.raises(GenerationProviderError, match="generation_schema_not_supported"):
        await runner(lambda _: pytest.fail("No model call authorized"), dialect="openai").generate(
            selected, policy=POLICY,
        )
