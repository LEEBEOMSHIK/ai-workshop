"""Independent runtime-option transmission, privacy and failure boundaries."""
import asyncio
import json
from dataclasses import replace
from types import MappingProxyType

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
from ai_workshop.labs.rag.models.orchestration_policy import resolve_orchestration_policy
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, runner
from tests.unit.labs.rag.orchestration.test_direct_answer_independent import reply, selected
from tests.unit.labs.rag.orchestration.test_model_timing_independent import PartialBody


@pytest.mark.parametrize("mode", ["manager_delegation", "direct_answer"])
@pytest.mark.parametrize("options", [
    {"version": 1, "num_batch": 256},
    {"version": 1, "num_thread": 10},
    {"version": 1, "num_batch": 256, "num_thread": 10},
])
async def test_only_explicit_numeric_options_change_and_citations_and_trace_remain(mode, options):
    async def execute(configuration):
        calls = []

        def handler(value):
            calls.append(json.loads(value.content))
            task = (configuration.question
                    if mode == "manager_delegation" and len(calls) == 1 else None)
            return reply(value, task=task)

        with capture_agent_trace(True):
            result = await runner(handler).generate(configuration, policy=POLICY)
            trace = current_agent_trace()
        return result, calls, trace

    expected = {k:v for k,v in options.items() if k != "version"}
    baseline, old_calls, _ = await execute(selected(mode))
    result, calls, trace = await execute(selected(mode, ollama_runtime=options))
    assert result.generation == baseline.generation
    assert len(calls) == (2 if mode == "manager_delegation" else 1)
    models = [span for span in trace.spans if span.kind == "model"]
    assert len(models) == len(calls)
    for current, old, model in zip(calls, old_calls, models, strict=True):
        assert {k:current["options"][k] for k in expected} == expected
        assert "version" not in current["options"]
        recorded = json.loads(model.input.text)
        assert recorded["options"] == current["options"]
        for key in expected:
            del current["options"][key]
        assert current == old
    restored = read_agent_trace({
        TRACE_STORAGE_KEY: persisted_agent_trace(trace).model_dump(mode="json"),
    })
    assert restored.spans[-1].citation_reference_map == models[-1].citation_reference_map
    assert "PRIVATE_THINKING_CANARY" not in trace.model_dump_json()


async def test_explicit_null_keeps_original_native_wire_bytes():
    calls = []

    def handler(value):
        calls.append(value.content)
        return reply(value)

    await runner(handler).generate(selected(), policy=POLICY)
    await runner(handler).generate(selected(ollama_runtime=None), policy=POLICY)
    assert len(calls) == 2 and calls[0] == calls[1]


def test_nested_frozen_profile_is_not_mutated_or_aliased():
    options = {"version": 1, "num_batch": 256}
    config = selected().profile.orchestration.model_dump()
    config["ollama_runtime"] = MappingProxyType(options)
    frozen = MappingProxyType({"orchestration": MappingProxyType(config)})
    policy = resolve_orchestration_policy(frozen)
    assert policy.ollama_runtime.num_batch == 256
    options["num_batch"] = 128
    assert policy.ollama_runtime.num_batch == 256
    assert frozen["orchestration"]["ollama_runtime"]["num_batch"] == 128


@pytest.mark.parametrize("failure", ["http", "timeout", "cancel"])
async def test_requested_options_survive_failure_or_cancel_without_retry(failure):
    calls = []
    stream = PartialBody()

    def handler(value):
        calls.append(value)
        if failure == "http":
            return httpx2.Response(500, request=value, content=b"PRIVATE_UPSTREAM_CANARY")
        return httpx2.Response(200, request=value, stream=stream)

    configuration = selected(ollama_runtime={"version": 1, "num_batch": 256, "num_thread": 10})
    if failure == "timeout":
        configuration = replace(
            configuration, profile=replace(configuration.profile, timeout_seconds=0.3),
        )
    with capture_agent_trace(True):
        task = asyncio.create_task(runner(handler).generate(configuration, policy=POLICY))
        if failure in {"cancel", "timeout"}:
            await asyncio.wait_for(stream.entered.wait(), 5)
        if failure == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(GenerationProviderError):
                await task
        trace = current_agent_trace()
    assert len(calls) == 1
    model = next(s for s in trace.spans if s.kind == "model")
    assert json.loads(model.input.text)["options"]["num_batch"] == 256
    assert json.loads(model.input.text)["options"]["num_thread"] == 10
    assert model.citation_reference_map.evidence_ids == tuple(
        e.evidence_id for e in configuration.evidence
    )
    assert model.state == ("cancelled" if failure == "cancel" else "failed")
    assert "PRIVATE_UPSTREAM_CANARY" not in trace.model_dump_json()
    if failure != "http":
        assert stream.closed


async def test_options_do_not_bypass_current_permission_denial():
    def forbidden(value):
        raise AssertionError("Denied request must not reach a provider")

    async def deny():
        raise AppError("not_found", "synthetic denied", 404)

    with pytest.raises(AppError):
        await runner(forbidden).generate(
            selected(ollama_runtime={"version": 1, "num_batch": 256}),
            policy=POLICY, revalidate=deny,
        )
