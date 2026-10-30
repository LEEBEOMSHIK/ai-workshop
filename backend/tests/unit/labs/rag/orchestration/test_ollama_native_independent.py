"""Independent native wire, timing provenance and incomplete-response contracts."""

import asyncio
import json
from dataclasses import replace

import httpx2
import pytest

from ai_workshop.labs.rag.executions.agent_trace import (
    TRACE_STORAGE_KEY,
    capture_agent_trace,
    current_agent_trace,
    next_agent_trace,
    persisted_agent_trace,
    read_agent_trace,
)
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    GenerationTermination,
    tracked_generation_call,
)
from tests.unit.labs.rag.orchestration.test_agents_sdk import (
    POLICY,
    answer,
    request,
    response,
    runner,
)
from tests.unit.labs.rag.orchestration.test_model_timing_independent import PartialBody
from tests.unit.labs.rag.orchestration.test_transport_limits import StreamingBody


def native_request():
    return request(local_http_api="ollama_chat")


def native_payload(value, *, delegate=False):
    message = {"role": "assistant", "content": json.dumps(answer())}
    if delegate:
        message = {"role": "assistant", "content": "", "tool_calls": [{
            "id": "call_native_synthetic_1",
            "function": {"name": "write_grounded_answer", "arguments": {"task": "Explain."}},
        }]}
    return {
        "model": json.loads(value.content)["model"], "done": True, "done_reason": "stop",
        "message": message, "total_duration": 12_000_000, "load_duration": 3_000_000,
        "prompt_eval_duration": 4_000_000, "eval_duration": 5_000_000,
        "prompt_eval_count": 30, "eval_count": 15,
    }


async def test_native_actual_wire_and_server_provenance_survive_metadata_storage():
    calls = []

    def handler(value):
        calls.append(value)
        return httpx2.Response(200, json=native_payload(value, delegate=len(calls) == 1),
                               request=value)

    with capture_agent_trace(True):
        result = await runner(handler).generate(native_request(), policy=POLICY)
        trace = current_agent_trace()
    assert result.generation is not None and len(calls) == 2
    assert result.execution.input_tokens == 60 and result.execution.output_tokens == 30
    models = [span for span in trace.spans if span.kind == "model"]
    for call, span in zip(calls, models, strict=True):
        wire = json.loads(call.content)
        assert call.url.path == "/api/chat" and wire["stream"] is False
        assert wire["options"]["num_predict"] == native_request().profile.max_output_tokens
        assert wire["options"]["temperature"] == native_request().profile.temperature
        assert wire["options"]["top_p"] == 1.0
        assert json.loads(span.input.text) == wire
        timing = span.model_timing
        assert timing.api == "ollama_chat" and timing.server_timing_status == "available"
        server = timing.server_timing
        assert server.source == "ollama_chat"
        assert (server.total_ms, server.load_ms, server.prompt_eval_ms, server.eval_ms) == (
            12.0, 3.0, 4.0, 5.0,
        )
    stored = persisted_agent_trace(trace)
    assert read_agent_trace({TRACE_STORAGE_KEY: stored.model_dump(mode="json")}) == stored
    assert all(span.input.text is None for span in stored.spans)
    # A later revision cannot rewrite the provider observations of a completed call.
    changed_spans = list(trace.spans)
    model_index = next(i for i, span in enumerate(changed_spans) if span.kind == "model")
    terminal = changed_spans[model_index]
    changed_timing = terminal.model_timing.model_copy(update={
        "server_timing": terminal.model_timing.server_timing.model_copy(update={"load_ms": 9.0}),
    })
    changed_spans[model_index] = terminal.model_copy(update={"model_timing": changed_timing})
    with pytest.raises(ValueError, match="Terminal"):
        next_agent_trace(trace.model_dump(mode="json"), trace.model_copy(update={
            "revision": trace.revision + 1, "spans": tuple(changed_spans),
        }))


@pytest.mark.parametrize("metric,expected", [
    (None, "missing"), (True, "invalid"), (-1, "invalid"), ("12", "invalid"),
    (2**53, "invalid"), (1.5, "invalid"),
])
async def test_optional_bad_native_metrics_do_not_change_answer_or_retry(metric, expected):
    calls = []

    def handler(value):
        calls.append(value)
        payload = native_payload(value, delegate=len(calls) == 1)
        if metric is None:
            payload.pop("load_duration")
        else:
            payload["load_duration"] = metric
        return httpx2.Response(200, json=payload, request=value)

    with capture_agent_trace(True):
        result = await runner(handler).generate(native_request(), policy=POLICY)
        trace = current_agent_trace()
    assert result.generation is not None and len(calls) == 2
    for span in trace.spans:
        if span.kind == "model":
            assert span.model_timing.server_timing_status == expected
            assert span.model_timing.server_timing is None


@pytest.mark.parametrize("cancel", [False, True])
async def test_native_partial_body_preserves_close_budget_and_unconfirmed_termination(cancel):
    stream = PartialBody()
    calls = []

    def handler(value):
        calls.append(value)
        return httpx2.Response(200, stream=stream, request=value)

    selected = native_request()
    if not cancel:
        selected = replace(selected, profile=replace(selected.profile, timeout_seconds=0.1))
    termination = GenerationTermination()
    with capture_agent_trace(True):
        task = asyncio.create_task(tracked_generation_call(
            runner(handler).generate(selected, policy=POLICY), termination,
        ))
        await asyncio.wait_for(stream.entered.wait(), 5)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(GenerationProviderError, match="provider_timeout"):
                await task
        trace = current_agent_trace()
    assert len(calls) == 1 and calls[0].url.path == "/api/chat"
    assert stream.closed and not termination.confirmed
    model = next(span for span in trace.spans if span.kind == "model")
    assert model.state == ("cancelled" if cancel else "failed")
    assert model.error_code == ("cancelled" if cancel else "provider_timeout")
    assert model.model_timing.api == "ollama_chat"
    assert model.model_timing.response_body_ms is None
    assert model.model_timing.server_timing is None


async def test_legacy_ollama_dialect_does_not_opt_into_native():
    calls = []

    def handler(value):
        calls.append(value)
        return response(value, delegate=len(calls) == 1)

    with capture_agent_trace(True):
        await runner(handler, dialect="ollama").generate(request(), policy=POLICY)
        trace = current_agent_trace()
    assert len(calls) == 2 and all(call.url.path == "/v1/chat/completions" for call in calls)
    for span in trace.spans:
        if span.kind == "model":
            assert span.model_timing.api == "openai_chat_completions"
            assert span.model_timing.server_timing is None
            assert span.model_timing.server_timing_status == "not_exposed_by_non_streaming_api"


async def test_native_wrong_runtime_dialect_is_rejected_before_any_call():
    calls = []

    def handler(value):
        calls.append(value)
        return response(value)

    with pytest.raises(GenerationProviderError, match="orchestration_not_supported"):
        await runner(handler, dialect="openai").generate(native_request(), policy=POLICY)
    assert calls == []


async def test_native_oversize_stops_receiving_without_confirming_termination():
    stream = StreamingBody()
    calls = []

    def handler(value):
        calls.append(value)
        return httpx2.Response(200, stream=stream, request=value)

    termination = GenerationTermination()
    with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
        await tracked_generation_call(
            runner(handler).generate(native_request(), policy=POLICY), termination,
        )
    assert len(calls) == 1 and calls[0].url.path == "/api/chat"
    assert stream.closed and stream.chunks <= 17
    assert not termination.confirmed


async def test_native_missing_tool_id_is_not_synthesized_or_retried():
    calls = []

    def handler(value):
        calls.append(value)
        payload = native_payload(value, delegate=True)
        del payload["message"]["tool_calls"][0]["id"]
        return httpx2.Response(200, json=payload, request=value)

    with pytest.raises(GenerationProviderError):
        await runner(handler).generate(native_request(), policy=POLICY)
    assert len(calls) == 1
