"""Independent request-local alias isolation and failure trace reconstruction."""
import asyncio
import json
from dataclasses import replace
from uuid import UUID

import httpx2
import pytest

from ai_workshop.labs.rag.executions.agent_trace import (
    TRACE_STORAGE_KEY,
    capture_agent_trace,
    current_agent_trace,
    persisted_agent_trace,
    read_agent_trace,
)
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from tests.unit.labs.rag.generation.test_source_reading import request_for, source_units
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, request, response, runner
from tests.unit.labs.rag.orchestration.test_model_timing_independent import PartialBody


def selected_request(identity):
    items = (replace(source_units(["Synthetic source e1 remains literal"])[0],
                     evidence_id=identity),)
    selected = request_for(items, reference="rag-answer-v6")
    return replace(selected, profile=replace(
        selected.profile, orchestration=request().profile.orchestration,
    ))


def alias_answer():
    return {"schema_version": 2, "status": "answered", "claims": [
        {"text": "Synthetic source e1 remains literal", "evidence_ids": ["e1"]},
    ]}


async def test_two_concurrent_requests_keep_e1_request_local_and_raw_trace_distinct():
    arrived = 0
    both = asyncio.Event()
    calls = []

    async def handler(value):
        nonlocal arrived
        body = json.loads(value.content)
        calls.append(body)
        if "tools" in body:
            return response(value, delegate=True)
        arrived += 1
        if arrived == 2:
            both.set()
        await asyncio.wait_for(both.wait(), 5)
        return response(value, content=alias_answer())

    target = runner(handler)

    async def execute(identity):
        with capture_agent_trace(True):
            result = await target.generate(selected_request(identity), policy=POLICY)
            return result, current_agent_trace()

    identities = (UUID(int=9001), UUID(int=9002))
    outputs = await asyncio.gather(*(execute(identity) for identity in identities))
    assert len(calls) == 4
    for identity, (result, trace) in zip(identities, outputs, strict=True):
        assert result.generation.claims[0].evidence_ids == (identity,)
        assert result.generation.claims[0].text == "Synthetic source e1 remains literal"
        models = [span for span in trace.spans if span.kind == "model"]
        assert models[0].citation_reference_map is None
        specialist = models[1]
        assert specialist.citation_reference_map.evidence_ids == (identity,)
        assert specialist.citation_reference_map.format == "rag-answer-v6"
        raw = json.loads(specialist.output.text)
        assert raw["claims"][0]["evidence_ids"] == ["e1"]
        agent = next(span for span in trace.spans if span.id == specialist.parent_id)
        assert json.loads(agent.output.text)["claims"][0]["evidence_ids"] == [str(identity)]
        metadata = persisted_agent_trace(trace)
        restored = read_agent_trace({TRACE_STORAGE_KEY: metadata.model_dump(mode="json")})
        assert restored.spans[specialist.sequence].citation_reference_map.evidence_ids == (
            identity,
        )


@pytest.mark.parametrize("cancel", [False, True])
async def test_unfinished_specialist_retains_mapping_before_response_and_after_failure(cancel):
    stream = PartialBody()
    calls = []

    def handler(value):
        calls.append(value)
        if "tools" in json.loads(value.content):
            return response(value, delegate=True)
        return httpx2.Response(200, stream=stream, request=value)

    identity = UUID(int=9010)
    selected = selected_request(identity)
    if not cancel:
        selected = replace(selected, profile=replace(selected.profile, timeout_seconds=0.15))
    with capture_agent_trace(True):
        task = asyncio.create_task(runner(handler).generate(selected, policy=POLICY))
        await asyncio.wait_for(stream.entered.wait(), 5)
        running = current_agent_trace()
        current = [span for span in running.spans if span.kind == "model"][-1]
        assert current.state == "running"
        assert current.citation_reference_map.evidence_ids == (identity,)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(GenerationProviderError, match="provider_timeout"):
                await task
        trace = current_agent_trace()
    model = [span for span in trace.spans if span.kind == "model"][-1]
    assert model.state == ("cancelled" if cancel else "failed")
    assert model.citation_reference_map.evidence_ids == (identity,)
    assert persisted_agent_trace(trace).spans[model.sequence].citation_reference_map == (
        model.citation_reference_map
    )
    assert stream.closed and len(calls) == 2
