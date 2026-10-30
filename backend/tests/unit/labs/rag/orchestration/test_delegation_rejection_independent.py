"""Independent rejection/privacy checks through the real SDK and mock HTTP only."""

import json

import httpx2
import pytest

from ai_workshop.labs.rag.executions.agent_trace import (
    TRACE_STORAGE_KEY,
    capture_agent_trace,
    current_agent_trace,
    persisted_agent_trace,
    read_agent_trace,
    storage_agent_trace,
)
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, request, runner
from tests.unit.labs.rag.orchestration.test_autonomous_handoffs import (
    autonomous_request,
    handoff_response,
)

REJECTED_BODY = "SYNTHETIC_REJECTED_CONTENT_DO_NOT_RETAIN"
REJECTED_TASK = "SYNTHETIC_REJECTED_TASK_DO_NOT_RETAIN"
UNKNOWN_NAME = "synthetic_unknown_tool_do_not_retain"
HIDDEN_REASONING = "SYNTHETIC_HIDDEN_REASONING_DO_NOT_RETAIN"


def rejected_response(value, case, *, manager=False):
    native = value.url.path.endswith("/api/chat")
    payload = handoff_response(value, "answer_specialist", task=REJECTED_TASK).json()
    choice = payload if native else payload["choices"][0]
    message = choice["message"]
    message["content"] = REJECTED_BODY
    message["thinking" if native else "reasoning"] = HIDDEN_REASONING
    call = message["tool_calls"][0]
    function = call["function"]
    if manager:
        function["name"] = "write_grounded_answer"
    if case == "missing":
        del message["tool_calls"]
        if not native:
            choice["finish_reason"] = "stop"
    elif case == "empty":
        message["tool_calls"] = []
        if not native:
            choice["finish_reason"] = "stop"
    elif case == "multiple":
        message["tool_calls"].append({**call, "id": "synthetic_other_call"})
    elif case == "unknown":
        function["name"] = UNKNOWN_NAME
    elif case == "self":
        function["name"] = "transfer_to_evidence_specialist"
    elif case == "finish":
        choice["done_reason" if native else "finish_reason"] = "length"
    elif case == "shape":
        call["id"] = {"invalid": REJECTED_TASK}
    elif case == "arguments_type":
        function["arguments"] = 7
    elif case == "extra":
        function["arguments"] = {"task": REJECTED_TASK, "other": REJECTED_TASK}
    elif case == "blank":
        function["arguments"] = {"task": "   "}
    elif case == "nontext":
        function["arguments"] = {"task": {"unexpected": REJECTED_TASK}}
    elif case == "long":
        function["arguments"] = {"task": REJECTED_TASK * 200}
    else:
        raise AssertionError(case)
    if not native and isinstance(function["arguments"], dict):
        function["arguments"] = json.dumps(function["arguments"])
    return httpx2.Response(200, json=payload, request=value)


CASES = [
    ("missing", "delegation_required_handoff_missing"),
    ("empty", "delegation_required_handoff_missing"),
    ("multiple", "delegation_multiple_tool_calls"),
    ("unknown", "delegation_unapproved_target"),
    ("self", "delegation_unapproved_target"),
    ("finish", "delegation_invalid_finish_reason"),
    ("shape", "delegation_malformed_tool_call"),
    ("arguments_type", "delegation_invalid_arguments"),
    ("extra", "delegation_invalid_task"),
    ("blank", "delegation_invalid_task"),
    ("nontext", "delegation_invalid_task"),
    ("long", "delegation_invalid_task"),
]


@pytest.mark.parametrize("api", ["openai_chat_completions", "ollama_chat"])
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("case,detail", CASES)
async def test_rejected_provider_output_is_never_retained_and_has_closed_reason(
    api, enabled, case, detail, caplog,
):
    calls = []

    def handler(value):
        calls.append(value)
        return rejected_response(value, case)

    with capture_agent_trace(enabled):
        with pytest.raises(GenerationProviderError) as caught:
            await runner(handler).generate(autonomous_request(api), policy=POLICY)
        trace = current_agent_trace()
    prior_provider_error = case in {"extra", "blank", "nontext", "long"} or (
        api == "ollama_chat" and case in {"shape", "arguments_type"}
    )
    assert caught.value.code == (
        "provider_invalid_response" if prior_provider_error else "orchestration_invalid_delegation"
    )
    assert caught.value.execution.input_tokens == 30
    assert caught.value.execution.output_tokens == 15
    assert len(calls) == 1
    assert trace is not None
    assert all(span.state == "failed" for span in trace.spans)
    model = next(span for span in trace.spans if span.kind == "model")
    assert model.error_code == detail
    assert model.model_timing is not None
    assert model.model_timing.response_validation_ms is not None
    assert all(span.output.text is None and span.output.sha256 is None for span in trace.spans)
    stored = storage_agent_trace(trace)
    assert read_agent_trace({TRACE_STORAGE_KEY: stored.model_dump(mode="json")}) == stored
    metadata = persisted_agent_trace(trace)
    serialized = stored.model_dump_json() + metadata.model_dump_json() + str(caught.value)
    for canary in (REJECTED_BODY, REJECTED_TASK, UNKNOWN_NAME, HIDDEN_REASONING):
        assert canary not in serialized
        assert canary not in caplog.text


@pytest.mark.parametrize("api", ["openai_chat_completions", "ollama_chat"])
@pytest.mark.parametrize("case,detail", [CASES[0], CASES[2], CASES[3], CASES[8]])
async def test_legacy_manager_keeps_error_contract_and_records_safe_reason(api, case, detail):
    calls = []

    def handler(value):
        calls.append(value)
        return rejected_response(value, case, manager=True)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError) as caught:
            await runner(handler).generate(request(local_http_api=api), policy=POLICY)
        trace = current_agent_trace()
    assert caught.value.code == (
        "provider_invalid_response" if case == "extra" else "orchestration_invalid_delegation"
    )
    assert len(calls) == 1
    assert next(span for span in trace.spans if span.kind == "model").error_code == detail
    assert REJECTED_TASK not in trace.model_dump_json()


@pytest.mark.parametrize("api", ["openai_chat_completions", "ollama_chat"])
async def test_later_rejection_preserves_completed_handoff_without_invalid_output(api):
    calls = []

    def handler(value):
        calls.append(value)
        if len(calls) == 1:
            return handoff_response(value, "review_specialist", task="Synthetic approved task")
        return rejected_response(value, "unknown")

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError, match="orchestration_invalid_delegation"):
            await runner(handler).generate(autonomous_request(api), policy=POLICY)
        trace = current_agent_trace()
    assert len(calls) == 2
    models = [span for span in trace.spans if span.kind == "model"]
    assert [span.state for span in models] == ["completed", "failed"]
    assert models[0].error_code is None
    assert models[1].error_code == "delegation_unapproved_target"
    assert models[1].output.text is None
    assert len([span for span in trace.spans if span.kind == "delegation"]) == 1
    assert all(span.state != "running" for span in trace.spans)
    assert UNKNOWN_NAME not in trace.model_dump_json()

    # Old records retain their aggregate code and do not gain inferred detail.
    historical = persisted_agent_trace(trace).model_dump(mode="json")
    historical.pop("content_retention")
    for span in historical["spans"]:
        if span["state"] == "failed":
            span["error_code"] = "orchestration_invalid_delegation"
    restored = read_agent_trace({TRACE_STORAGE_KEY: historical})
    assert restored is not None
    assert all(span.error_code == "orchestration_invalid_delegation"
               for span in restored.spans if span.state == "failed")
    assert all(span.output.text is None for span in restored.spans)


@pytest.mark.parametrize("api", ["openai_chat_completions", "ollama_chat"])
@pytest.mark.parametrize("calls_value", [None, []])
async def test_absent_handoff_is_not_misclassified_as_a_final_answer(api, calls_value):
    calls = []

    def handler(value):
        calls.append(value)
        payload = handoff_response(value, None).json()
        choice = payload if api == "ollama_chat" else payload["choices"][0]
        choice["message"]["tool_calls"] = calls_value
        return httpx2.Response(200, json=payload, request=value)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError) as caught:
            await runner(handler).generate(autonomous_request(api), policy=POLICY)
        trace = current_agent_trace()
    assert len(calls) == 1
    # Native null is an invalid native call envelope, whereas [] means no handoff.
    if api == "ollama_chat" and calls_value is None:
        assert caught.value.code == "provider_invalid_response"
    else:
        assert caught.value.code == "orchestration_invalid_delegation"
        assert next(span for span in trace.spans if span.kind == "model").error_code == (
            "delegation_required_handoff_missing"
        )
    assert all(span.output.text is None for span in trace.spans)


@pytest.mark.parametrize("api", ["openai_chat_completions", "ollama_chat"])
async def test_direct_answer_still_rejects_unapproved_tool_output_with_provider_error(api):
    calls = []

    def handler(value):
        calls.append(value)
        return rejected_response(value, "unknown")

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError) as caught:
            await runner(handler).generate(
                request(dispatch_mode="direct_answer", local_http_api=api), policy=POLICY,
            )
        trace = current_agent_trace()
    assert caught.value.code == "provider_invalid_response"
    assert len(calls) == 1
    assert all(span.output.text is None for span in trace.spans)
    assert UNKNOWN_NAME not in trace.model_dump_json()


@pytest.mark.parametrize("api", ["openai_chat_completions", "ollama_chat"])
@pytest.mark.parametrize("calls_value", [{}, 0, "", False])
async def test_falsy_invalid_call_container_is_classified_as_malformed(api, calls_value):
    def handler(value):
        payload = handoff_response(value, None).json()
        choice = payload if api == "ollama_chat" else payload["choices"][0]
        choice["message"]["tool_calls"] = calls_value
        return httpx2.Response(200, json=payload, request=value)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError) as caught:
            await runner(handler).generate(autonomous_request(api), policy=POLICY)
        trace = current_agent_trace()
    assert caught.value.code == (
        "provider_invalid_response" if api == "ollama_chat" else "orchestration_invalid_delegation"
    )
    model = next(span for span in trace.spans if span.kind == "model")
    assert model.error_code == "delegation_malformed_tool_call"
    assert model.output.text is None


@pytest.mark.parametrize("api", ["openai_chat_completions", "ollama_chat"])
async def test_missing_handoff_has_priority_over_truncated_finish_reason(api):
    def handler(value):
        payload = handoff_response(value, None).json()
        choice = payload if api == "ollama_chat" else payload["choices"][0]
        choice["done_reason" if api == "ollama_chat" else "finish_reason"] = "length"
        return httpx2.Response(200, json=payload, request=value)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError, match="orchestration_invalid_delegation"):
            await runner(handler).generate(autonomous_request(api), policy=POLICY)
        trace = current_agent_trace()
    assert next(span for span in trace.spans if span.kind == "model").error_code == (
        "delegation_required_handoff_missing"
    )
