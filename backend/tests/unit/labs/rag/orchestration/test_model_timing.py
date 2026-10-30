"""Measure client boundaries without changing inference requests or fabricating server time."""

import json

import httpx2
import pytest

from ai_workshop.labs.rag.executions.agent_trace import capture_agent_trace, current_agent_trace
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.orchestration import model_transport
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, request, response, runner


async def test_model_calls_retain_transport_and_validation_times_without_changing_requests():
    calls = []

    def handler(value):
        calls.append(json.loads(value.content))
        return response(value, delegate=len(calls) == 1)

    with capture_agent_trace(True):
        await runner(handler).generate(request(), policy=POLICY)
        trace = current_agent_trace()
    models = [span for span in trace.spans if span.kind == "model"]
    assert len(models) == len(calls) == 2
    assert calls[0]["tool_choice"] == "required"
    assert all(call.get("stream", False) is False for call in calls)
    for model in models:
        assert hasattr(model, "model_timing"), "Model timing must be retained"
        timing = model.model_timing
        assert timing is not None
        assert timing.request_duration_ms >= timing.response_body_ms >= timing.response_headers_ms
        assert timing.response_validation_ms >= 0
        assert timing.server_timing_status == "not_exposed_by_non_streaming_api"
        assert "PRIVATE_REASONING_CANARY" not in timing.model_dump_json()


async def test_connect_failure_retains_elapsed_wait_without_inventing_received_response():
    calls = []

    def handler(value):
        calls.append(value)
        raise httpx2.ConnectError("PRIVATE_CONNECTION_CANARY", request=value)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError):
            await runner(handler).generate(request(), policy=POLICY)
        trace = current_agent_trace()
    model = next(span for span in trace.spans if span.kind == "model")
    assert hasattr(model, "model_timing"), "Failed requests also need timing"
    assert len(calls) == 1
    assert model.state == "failed"
    timing = model.model_timing
    assert timing.request_duration_ms >= 0
    assert timing.response_headers_ms is timing.response_body_ms is None
    assert timing.response_validation_ms is None
    assert "PRIVATE_CONNECTION_CANARY" not in trace.model_dump_json()


async def test_monotonic_boundaries_include_httpx_body_close_and_separate_validation(monkeypatch):
    clock = [0.0]
    calls = []
    original_output = model_transport._response_output
    monkeypatch.setattr(model_transport, "perf_counter", lambda: clock[0])

    class Body(httpx2.AsyncByteStream):
        def __init__(self, content):
            self.content = content

        async def __aiter__(self):
            clock[0] += 3
            yield self.content

        async def aclose(self):
            clock[0] += 2

    def handler(value):
        calls.append(value)
        clock[0] += 2
        payload = response(value, delegate=len(calls) == 1).content
        return httpx2.Response(200, stream=Body(payload), request=value)

    def validate(*args, **kwargs):
        clock[0] += 4
        return original_output(*args, **kwargs)

    monkeypatch.setattr(model_transport, "_response_output", validate)
    with capture_agent_trace(True):
        await runner(handler).generate(request(), policy=POLICY)
        trace = current_agent_trace()
    for model in [span for span in trace.spans if span.kind == "model"]:
        timing = model.model_timing
        assert timing.response_headers_ms == 2000
        # httpx2 aiter_raw closes its stream before aiter_bytes finishes at EOF.
        assert timing.response_body_ms == 7000
        assert timing.request_duration_ms == 7000
        assert timing.response_validation_ms == 4000


async def test_invalid_clock_only_marks_observation_incomplete(monkeypatch):
    calls = []

    def handler(value):
        calls.append(value)
        return response(value, delegate=len(calls) == 1)

    monkeypatch.setattr(model_transport, "perf_counter", lambda: float("nan"))
    with capture_agent_trace(True):
        result = await runner(handler).generate(request(), policy=POLICY)
        trace = current_agent_trace()
    assert result.generation is not None and len(calls) == 2
    assert not trace.observation_complete
    assert all(span.model_timing is None for span in trace.spans)
