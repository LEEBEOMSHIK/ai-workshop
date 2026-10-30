"""Closed rejection diagnostics without retaining rejected model output."""

import json

import httpx2
import pytest
from agents import Agent
from agents.run_context import RunContextWrapper

from ai_workshop.labs.rag.executions.agent_trace import capture_agent_trace, current_agent_trace
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.orchestration.sdk_hooks import ObservationHooks
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, request, runner
from tests.unit.labs.rag.orchestration.test_autonomous_handoffs import (
    autonomous_request,
    handoff_response,
)

CANARY = "REJECTED_MODEL_OUTPUT_CANARY"


@pytest.mark.parametrize("api", ["openai_chat_completions", "ollama_chat"])
@pytest.mark.parametrize("dispatch", ["autonomous", "manager"])
@pytest.mark.parametrize(("invalid", "detail"), [
    ("missing", "delegation_required_handoff_missing"),
    ("empty", "delegation_required_handoff_missing"),
    ("multiple", "delegation_multiple_tool_calls"),
    ("calls_object", "delegation_malformed_tool_call"),
    ("call_scalar", "delegation_malformed_tool_call"),
    ("empty_id", "delegation_malformed_tool_call"),
    ("missing_function", "delegation_malformed_tool_call"),
    ("unknown_target", "delegation_unapproved_target"),
    ("length", "delegation_invalid_finish_reason"),
    ("arguments_type", "delegation_invalid_arguments"),
    ("blank_task", "delegation_invalid_task"),
    ("extra_argument", "delegation_invalid_task"),
    ("long_task", "delegation_invalid_task"),
])
async def test_rejected_model_records_closed_reason_usage_and_timing(
    api, dispatch, invalid, detail,
):
    calls = []
    native = api == "ollama_chat"

    def handler(value):
        calls.append(value)
        payload = handoff_response(value, "answer_specialist").json()
        message = payload["message"] if native else payload["choices"][0]["message"]
        message["content"] = CANARY
        message["thinking" if native else "reasoning"] = CANARY
        tool = message["tool_calls"][0]
        if dispatch == "manager":
            tool["function"]["name"] = "write_grounded_answer"
        if invalid == "missing":
            del message["tool_calls"]
        elif invalid == "empty":
            message["tool_calls"] = []
        elif invalid == "multiple":
            message["tool_calls"].append(tool.copy())
        elif invalid == "calls_object":
            message["tool_calls"] = {"private": CANARY}
        elif invalid == "call_scalar":
            message["tool_calls"] = [CANARY]
        elif invalid == "empty_id":
            tool["id"] = ""
        elif invalid == "missing_function":
            tool["function"] = CANARY
        elif invalid == "unknown_target":
            tool["function"]["name"] = CANARY
        elif invalid == "length":
            if native:
                payload["done_reason"] = "length"
            else:
                payload["choices"][0]["finish_reason"] = "length"
        elif invalid == "arguments_type":
            tool["function"]["arguments"] = CANARY if native else {"private": CANARY}
        else:
            args = ({"task": " "} if invalid == "blank_task" else
                    {"task": CANARY, "private": CANARY} if invalid == "extra_argument" else
                    {"task": CANARY * 200})
            tool["function"]["arguments"] = args if native else json.dumps(args)
        return httpx2.Response(200, json=payload, request=value)

    selected = (autonomous_request(api) if dispatch == "autonomous" else
                request(local_http_api=api))
    old_generic = invalid in {"blank_task", "extra_argument", "long_task"} or (
        native and invalid in {
            "calls_object", "call_scalar", "empty_id", "missing_function", "arguments_type",
        }
    )
    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError) as caught:
            await runner(handler).generate(selected, policy=POLICY)
        trace = current_agent_trace()
    assert caught.value.code == (
        "provider_invalid_response" if old_generic else "orchestration_invalid_delegation"
    )
    assert not caught.value.retryable
    assert len(calls) == 1
    model = next(span for span in trace.spans if span.kind == "model")
    assert model.error_code == detail
    assert model.state == "failed"
    assert model.input_tokens == 30 and model.output_tokens == 15
    assert model.model_timing is not None
    assert model.model_timing.response_validation_ms is not None
    assert model.output.text is None and model.output.sha256 is None
    assert all(span.state == "failed" for span in trace.spans)
    assert caught.value.execution.input_tokens == 30
    assert caught.value.execution.output_tokens == 15
    assert CANARY not in trace.model_dump_json()
    assert CANARY not in str(caught.value)


@pytest.mark.parametrize("arguments", ["{", '{"task":"a","task":"b"}', '{"task":NaN}'])
async def test_invalid_argument_json_keeps_provider_error_and_safe_detail(arguments):
    def handler(value):
        payload = handoff_response(value, "answer_specialist").json()
        payload["choices"][0]["message"]["tool_calls"][0]["function"]["arguments"] = arguments
        return httpx2.Response(200, json=payload)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
            await runner(handler).generate(autonomous_request(), policy=POLICY)
        trace = current_agent_trace()
    assert next(span for span in trace.spans if span.kind == "model").error_code == (
        "delegation_invalid_arguments"
    )


@pytest.mark.parametrize("calls", [{}, 0, "", False])
async def test_falsy_malformed_calls_are_distinct_from_missing_required_handoff(calls):
    def handler(value):
        payload = handoff_response(value, "answer_specialist").json()
        payload["choices"][0]["message"]["tool_calls"] = calls
        return httpx2.Response(200, json=payload)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError, match="orchestration_invalid_delegation"):
            await runner(handler).generate(autonomous_request(), policy=POLICY)
        trace = current_agent_trace()
    assert next(span for span in trace.spans if span.kind == "model").error_code == (
        "delegation_malformed_tool_call"
    )


@pytest.mark.parametrize("invalid", ["duplicate_agent", "unknown_agent", "self_handoff",
                                      "missing_task", "tool_context", "tool_end"])
async def test_invalid_sdk_transition_finishes_open_spans_with_safe_reason(monkeypatch, invalid):
    orchestrator = runner(lambda _: pytest.fail("No HTTP request expected"))

    async def invalid_run(state, runtime):
        hooks = ObservationHooks()
        context = RunContextWrapper(state)
        source = Agent(name="evidence_specialist")
        await hooks.on_agent_start(context, source)
        if invalid == "duplicate_agent":
            await hooks.on_agent_start(context, source)
        elif invalid == "unknown_agent":
            await hooks.on_agent_start(context, Agent(name=CANARY))
        elif invalid in {"self_handoff", "missing_task"}:
            state.handoff_task = "Synthetic task" if invalid == "self_handoff" else None
            await hooks.on_handoff(context, source, source if invalid == "self_handoff" else
                                   Agent(name="answer_specialist"))
        elif invalid == "tool_context":
            await hooks.on_tool_start(context, source, None)
        else:
            await hooks.on_tool_end(context, source, None, CANARY)

    monkeypatch.setattr(orchestrator, "_run", invalid_run)
    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError, match="orchestration_invalid_delegation"):
            await orchestrator.generate(autonomous_request(), policy=POLICY)
        trace = current_agent_trace()
    assert all(span.state == "failed" for span in trace.spans)
    assert all(span.error_code == "delegation_invalid_sdk_transition" for span in trace.spans)
    assert CANARY not in trace.model_dump_json()


@pytest.mark.parametrize("dispatch", ["direct_answer", "manager_delegation"])
@pytest.mark.parametrize(("field", "value", "code"), [
    ("model", "synthetic-other-model", "provider_model_mismatch"),
    ("done", False, "provider_invalid_response"),
])
async def test_unrelated_native_envelope_failure_keeps_previous_unknown_usage(
    dispatch, field, value, code,
):
    def handler(wire_request):
        payload = handoff_response(wire_request, "answer_specialist").json()
        payload[field] = value
        return httpx2.Response(200, json=payload)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError) as caught:
            await runner(handler).generate(
                request(local_http_api="ollama_chat", dispatch_mode=dispatch), policy=POLICY,
            )
        trace = current_agent_trace()
    assert caught.value.code == code
    assert caught.value.execution.input_tokens is None
    assert caught.value.execution.output_tokens is None
    assert all(span.error_code == code for span in trace.spans)
