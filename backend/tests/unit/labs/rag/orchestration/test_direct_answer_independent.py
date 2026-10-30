"""Independent native SDK direct-dispatch contracts; no real network or models."""
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
from ai_workshop.labs.rag.generation.domain import ConversationRole, ConversationTurn
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.models.orchestration_policy import OrchestrationPolicy
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, runner
from tests.unit.labs.rag.orchestration.test_model_timing_independent import PartialBody
from tests.unit.labs.rag.orchestration.test_reference_packing_independent import (
    alias_answer,
    selected_request,
)


def selected(mode="direct_answer", **limits):
    value = selected_request(UUID(int=4901))
    policy = value.profile.orchestration.model_dump()
    policy.update(local_http_api="ollama_chat", dispatch_mode=mode, **limits)
    return replace(value, question="Original synthetic question", resolved_query="Resolved query",
                   history=(ConversationTurn(ConversationRole.USER, "Earlier synthetic question"),),
                   profile=replace(value.profile, orchestration=OrchestrationPolicy(**policy)))


def reply(value, *, task=None, content=None):
    message = {"role": "assistant", "content": json.dumps(
        alias_answer() if content is None else content,
    ), "thinking": "PRIVATE_THINKING_CANARY"}
    if task is not None:
        message.update(content="", tool_calls=[{"id": "call_direct_compare", "function": {
            "name": "write_grounded_answer", "arguments": {"task": task},
        }}])
    return httpx2.Response(200, request=value, json={
        "model": json.loads(value.content)["model"],
        "done": True, "done_reason": "stop", "message": message,
        "prompt_eval_count": 7, "eval_count": 3,
        "total_duration": 100_000_000, "load_duration": 10_000_000,
        "prompt_eval_duration": 60_000_000, "eval_duration": 20_000_000,
    })


async def test_native_direct_wire_equals_same_task_manager_and_has_real_two_span_trace():
    direct_calls, manager_calls = [], []
    access = []

    async def authorize():
        access.append(True)

    def direct(value):
        direct_calls.append(value.content)
        return reply(value)

    def manager(value):
        manager_calls.append(value.content)
        return reply(value, task=selected().question if len(manager_calls) == 1 else None)

    with capture_agent_trace(True):
        result = await runner(direct).generate(selected(), policy=POLICY, revalidate=authorize)
        trace = current_agent_trace()
    with capture_agent_trace(True):
        old = await runner(manager).generate(selected("manager_delegation"), policy=POLICY)
        old_trace = current_agent_trace()
    assert len(direct_calls) == 1 and len(manager_calls) == 2 and len(access) == 1
    assert direct_calls[0] == manager_calls[1]
    payload = json.loads(json.loads(direct_calls[0])["messages"][-1]["content"])
    assert payload["question"] == "Original synthetic question"
    assert payload["resolved_query"] == "Resolved query"
    assert payload["delegated_task"] == payload["question"]
    assert payload["history"] == [{"role": "user", "content": "Earlier synthetic question"}]
    assert result.generation == old.generation
    assert result.generation.claims[0].evidence_ids == (UUID(int=4901),)
    assert len(trace.spans) == 2 and len(old_trace.spans) == 5
    agent, model = trace.spans
    assert agent.kind == "agent" and agent.name == "answer_specialist"
    assert model.kind == "model" and model.parent_id == agent.id
    assert all(span.state == "completed" for span in trace.spans)
    assert model.citation_reference_map.evidence_ids == (UUID(int=4901),)
    assert json.loads(model.output.text)["claims"][0]["evidence_ids"] == ["e1"]
    assert json.loads(agent.output.text)["claims"][0]["evidence_ids"] == [str(UUID(int=4901))]
    stored = persisted_agent_trace(trace)
    restored = read_agent_trace({TRACE_STORAGE_KEY: stored.model_dump(mode="json")})
    assert restored.spans[1].citation_reference_map == model.citation_reference_map
    assert "PRIVATE_THINKING_CANARY" not in trace.model_dump_json()
    assert result.execution.input_tokens == 7 and result.execution.output_tokens == 3


@pytest.mark.parametrize("content", [
    {"schema_version": 2, "status": "answered", "claims": [
        {"text": "Synthetic", "evidence_ids": ["e999"]},
    ]},
    {"unexpected": "malformed"},
])
async def test_direct_invalid_output_has_no_manager_fallback_and_retains_mapping(content):
    calls = []

    def handler(value):
        calls.append(value)
        return reply(value, content=content)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError):
            await runner(handler).generate(selected(), policy=POLICY)
        trace = current_agent_trace()
    assert len(calls) == 1 and len(trace.spans) == 2
    assert trace.spans[1].citation_reference_map.evidence_ids == (UUID(int=4901),)
    assert trace.spans[0].state == "failed"


@pytest.mark.parametrize("cancel", [False, True])
async def test_direct_partial_body_timeout_or_cancel_retains_map_and_closes(cancel):
    stream = PartialBody()
    calls = []

    def handler(value):
        calls.append(value)
        return httpx2.Response(200, request=value, stream=stream)

    value = selected()
    if not cancel:
        value = replace(value, profile=replace(value.profile, timeout_seconds=0.15))
    with capture_agent_trace(True):
        task = asyncio.create_task(runner(handler).generate(value, policy=POLICY))
        await asyncio.wait_for(stream.entered.wait(), 5)
        trace = current_agent_trace()
        assert len(trace.spans) == 2
        assert trace.spans[1].citation_reference_map.evidence_ids == (UUID(int=4901),)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(GenerationProviderError, match="provider_timeout"):
                await task
        trace = current_agent_trace()
    assert len(calls) == 1 and stream.closed
    assert all(s.state == ("cancelled" if cancel else "failed") for s in trace.spans)


async def test_direct_current_permission_denial_makes_no_http_call():
    def forbidden(value):
        raise AssertionError("Denied access must not invoke a provider")

    async def deny():
        raise AppError("not_found", "synthetic denied", 404)

    with pytest.raises(AppError):
        await runner(forbidden).generate(selected(), policy=POLICY, revalidate=deny)


@pytest.mark.parametrize("prior_calls,allowed", [(0, True), (1, False)])
async def test_direct_prior_model_call_counts_against_one_call_limit(prior_calls, allowed):
    calls = []

    def handler(value):
        calls.append(value)
        return reply(value)

    value = selected(max_model_calls=1)
    if allowed:
        await runner(handler).generate(value, policy=POLICY, prior_model_calls=prior_calls)
        assert len(calls) == 1
    else:
        with pytest.raises(GenerationProviderError, match="orchestration_budget_exceeded"):
            await runner(handler).generate(value, policy=POLICY, prior_model_calls=prior_calls)
        assert not calls


@pytest.mark.parametrize("extra,allowed", [(0, True), (1, False)])
async def test_direct_prior_reserved_output_is_included(extra, allowed):
    calls = []

    def handler(value):
        calls.append(value)
        return reply(value)

    output_limit = selected().profile.max_output_tokens
    value = selected(max_model_calls=2, max_total_output_tokens=output_limit * 2)
    kwargs = dict(policy=POLICY, prior_model_calls=1,
                  prior_reserved_output_tokens=output_limit + extra)
    if allowed:
        await runner(handler).generate(value, **kwargs)
        assert len(calls) == 1
    else:
        with pytest.raises(GenerationProviderError, match="orchestration_budget_exceeded"):
            await runner(handler).generate(value, **kwargs)
        assert not calls
