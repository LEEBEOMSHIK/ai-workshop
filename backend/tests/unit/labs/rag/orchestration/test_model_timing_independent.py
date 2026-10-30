"""Independent synthetic transport and stored diagnostic compatibility checks."""

import asyncio
from dataclasses import replace

import httpx2
import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.executions.agent_trace import (
    TRACE_STORAGE_KEY,
    capture_agent_trace,
    current_agent_trace,
    persisted_agent_trace,
    read_agent_trace,
)
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, request, response, runner


class PartialBody(httpx2.AsyncByteStream):
    def __init__(self):
        self.entered = asyncio.Event()
        self.closed = False

    async def __aiter__(self):
        yield b'{"synthetic":'
        self.entered.set()
        await asyncio.Event().wait()

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("cancel", [False, True])
async def test_partial_body_keeps_headers_and_original_timeout_or_cancel_semantics(cancel):
    stream = PartialBody()
    calls = []

    def handler(value):
        calls.append(value)
        return httpx2.Response(200, stream=stream, request=value)

    selected = request()
    if not cancel:
        selected = replace(selected, profile=replace(selected.profile, timeout_seconds=0.1))
    # The capture object is shared into the child task while its context is copied.
    with capture_agent_trace(True):
        task = asyncio.create_task(runner(handler).generate(selected, policy=POLICY))
        await asyncio.wait_for(stream.entered.wait(), 5)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(GenerationProviderError, match="provider_timeout"):
                await task
        trace = current_agent_trace()
    assert stream.closed and len(calls) == 1
    models = [span for span in trace.spans if span.kind == "model"]
    assert len(models) == 1
    model = models[0]
    assert model.state == ("cancelled" if cancel else "failed")
    assert model.error_code == ("cancelled" if cancel else "provider_timeout")
    timing = model.model_timing
    assert timing is not None
    assert 0 <= timing.response_headers_ms <= timing.request_duration_ms
    assert timing.response_body_ms is None
    assert timing.response_validation_ms is None
    assert all(span.state != "running" for span in trace.spans)


async def test_malformed_completed_body_keeps_receive_marks_without_exposing_body():
    def handler(value):
        return httpx2.Response(200, content=b"SYNTHETIC_PRIVATE_INVALID_JSON", request=value)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
            await runner(handler).generate(request(), policy=POLICY)
        trace = current_agent_trace()
    model = next(span for span in trace.spans if span.kind == "model")
    timing = model.model_timing
    assert model.state == "failed" and timing is not None
    assert 0 <= timing.response_headers_ms <= timing.response_body_ms <= timing.request_duration_ms
    assert timing.response_validation_ms is not None
    assert "SYNTHETIC_PRIVATE_INVALID_JSON" not in trace.model_dump_json()


async def test_success_metadata_storage_preserves_timing_and_legacy_trace_stays_readable():
    calls = []

    def handler(value):
        calls.append(value)
        return response(value, delegate=len(calls) == 1)

    with capture_agent_trace(True):
        await runner(handler).generate(request(), policy=POLICY)
        trace = current_agent_trace()
    assert len(calls) == 2
    stored = persisted_agent_trace(trace)
    restored = read_agent_trace({TRACE_STORAGE_KEY: stored.model_dump(mode="json")})
    assert restored == stored
    models = [span for span in restored.spans if span.kind == "model"]
    assert len(models) == 2
    for span in models:
        timing = span.model_timing
        assert timing is not None
        assert timing.server_timing_status == "not_exposed_by_non_streaming_api"
        assert 0 <= timing.response_headers_ms <= timing.response_body_ms
        assert timing.response_body_ms <= timing.request_duration_ms
        assert timing.response_validation_ms >= 0
        assert span.input.text is None and span.output.text is None
    assert "PRIVATE_REASONING_CANARY" not in restored.model_dump_json()
    legacy = stored.model_dump(mode="json")
    for span in legacy["spans"]:
        span.pop("model_timing", None)
    old = read_agent_trace({TRACE_STORAGE_KEY: legacy})
    assert all(span.model_timing is None for span in old.spans)


@pytest.mark.parametrize("invalid", [float("nan"), float("inf"), -1, True, "1.0"])
@pytest.mark.parametrize("field", [
    "request_duration_ms", "response_headers_ms", "response_body_ms", "response_validation_ms",
])
def test_numeric_timing_metadata_rejects_coercion_and_nonfinite_values(field, invalid):
    from ai_workshop.labs.rag.executions.model_timing import ModelCallTiming

    values = dict(request_duration_ms=4.0, response_headers_ms=1.0,
                  response_body_ms=2.0, response_validation_ms=1.0)
    values[field] = invalid
    with pytest.raises(ValidationError):
        ModelCallTiming.model_validate(values)


@pytest.mark.parametrize("values", [
    {"request_duration_ms": 1.0, "response_headers_ms": 2.0},
    {"request_duration_ms": 4.0, "response_headers_ms": 3.0, "response_body_ms": 2.0},
    {"request_duration_ms": 4.0, "response_body_ms": 2.0},
    {"request_duration_ms": 4.0, "response_validation_ms": 2.0},
    {"request_duration_ms": 4.0, "server_header": "SYNTHETIC_PRIVATE_HEADER"},
])
def test_timing_rejects_impossible_milestones_and_unapproved_metadata(values):
    from ai_workshop.labs.rag.executions.model_timing import ModelCallTiming

    with pytest.raises(ValidationError):
        ModelCallTiming.model_validate(values)
