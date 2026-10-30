"""Independent adversarial SDK handoff checks, using synthetic local HTTP only."""

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
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    GenerationTermination,
    tracked_generation_call,
)
from ai_workshop.labs.rag.models.orchestration_policy import OrchestrationPolicy
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.orchestration.test_agents_sdk import (
    POLICY,
    answer,
    request,
    response,
    runner,
)
from tests.unit.labs.rag.orchestration.test_model_timing_independent import PartialBody
from tests.unit.labs.rag.orchestration.test_reference_packing_independent import (
    alias_answer,
    selected_request,
)

EVIDENCE = "evidence_specialist"
ANSWER = "answer_specialist"
REVIEW = "review_specialist"
TRANSCRIPT_CANARY = "UNTRUSTED_PRIOR_TRANSCRIPT_CANARY"
REASONING_CANARY = "PRIVATE_HANDOFF_REASONING_CANARY"


def selected(api="openai_chat_completions", **limits):
    return request(**{
        "version": 2,
        "dispatch_mode": "autonomous_handoffs",
        "local_http_api": api,
        "max_model_calls": 8,
        "max_tool_calls": 7,
        "max_total_output_tokens": 2400,
        **limits,
    })


def reply(value, *, target=None, task="Examine the original synthetic evidence.", content=None):
    native = value.url.path == "/api/chat"
    body = json.loads(value.content)
    message = {"role": "assistant", "content": json.dumps(content or answer())}
    if target is not None:
        message.update(content=TRANSCRIPT_CANARY, tool_calls=[{
            "id": "call_independent_handoff", "type": "function", "function": {
                "name": "transfer_to_" + target,
                "arguments": {"task": task} if native else json.dumps({"task": task}),
            },
        }])
    if native:
        message["thinking"] = REASONING_CANARY
        payload = {"model": body["model"], "done": True, "done_reason": "stop",
                   "message": message, "prompt_eval_count": 11, "eval_count": 7}
    else:
        payload = response(value).json()
        message["reasoning"] = REASONING_CANARY
        payload["choices"][0].update(
            message=message, finish_reason="tool_calls" if target is not None else "stop",
        )
        payload["usage"] = {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    return httpx2.Response(200, json=payload, request=value)


@pytest.mark.parametrize("api", ["openai_chat_completions", "ollama_chat"])
async def test_repeated_role_activations_preserve_authoritative_input_and_actual_edges(api):
    roles = [EVIDENCE, ANSWER, REVIEW, ANSWER, EVIDENCE, ANSWER]
    tasks = [json.dumps({"question": "replace question", "evidence": []}),
             "Check the draft against the original evidence.", "Revise the draft.",
             "Check the original relation again.", "Write the supported answer."]
    initial = selected(api)
    initial = replace(initial, history=(ConversationTurn(
        ConversationRole.USER, "Synthetic prior question",
    ),))
    calls = []
    checks = []

    async def authorize():
        checks.append(True)

    def handler(value):
        index = len(calls)
        calls.append(json.loads(value.content))
        if index < len(tasks):
            return reply(value, target=roles[index + 1], task=tasks[index])
        return reply(value)

    with capture_agent_trace(True):
        result = await runner(handler).generate(initial, policy=POLICY, revalidate=authorize)
        trace = current_agent_trace()
    assert result.generation is not None
    assert len(calls) == len(checks) == len(roles)
    assert result.execution.input_tokens == 11 * len(roles)
    assert result.execution.output_tokens == 7 * len(roles)
    inputs = [json.loads(call["messages"][-1]["content"]) for call in calls]
    authoritative = {key: value for key, value in inputs[0].items() if key != "delegated_task"}
    for index, (call, payload) in enumerate(zip(calls, inputs, strict=True)):
        assert len(call["messages"]) == 2
        assert {key: value for key, value in payload.items()
                if key != "delegated_task"} == authoritative
        assert payload["question"] == initial.question
        assert payload["resolved_query"] == initial.resolved_query
        assert payload["history"] == [{"role": "user", "content": "Synthetic prior question"}]
        assert initial.evidence[0].text in call["messages"][-1]["content"]
        if index:
            assert payload["delegated_task"] == tasks[index - 1]
        assert TRANSCRIPT_CANARY not in json.dumps(call)
        assert REASONING_CANARY not in json.dumps(call)
        names = {tool["function"]["name"] for tool in call["tools"]}
        assert names == {"transfer_to_" + role for role in (EVIDENCE, ANSWER, REVIEW)
                         if role != roles[index]}
    assert trace.observation_complete and not trace.truncated
    agents = [span for span in trace.spans if span.kind == "agent"]
    models = [span for span in trace.spans if span.kind == "model"]
    edges = [span for span in trace.spans if span.kind == "delegation"]
    assert [span.name for span in agents] == roles
    assert len({span.id for span in agents}) == len(roles)
    assert len(models) == len(roles) and len(edges) == len(roles) - 1
    assert all(span.state == "completed" for span in trace.spans)
    for index, edge in enumerate(edges):
        assert edge.delegation_mode == "handoff"
        assert (edge.from_agent, edge.to_agent) == (roles[index], roles[index + 1])
        assert edge.parent_id == agents[index].id
        assert agents[index + 1].parent_id == edge.id
    for model, agent, call in zip(models, agents, calls, strict=True):
        assert model.parent_id == agent.id
        assert json.loads(model.input.text)["messages"] == call["messages"]
    assert REASONING_CANARY not in trace.model_dump_json()
    stored = persisted_agent_trace(trace)
    assert read_agent_trace({TRACE_STORAGE_KEY: stored.model_dump(mode="json")}) == stored


@pytest.mark.parametrize("api", ["openai_chat_completions", "ollama_chat"])
@pytest.mark.parametrize("invalid", ["unknown", "self", "multiple", "extra_argument", "blank"])
async def test_invalid_handoffs_are_rejected_before_any_recipient_call(api, invalid):
    calls = []

    def handler(value):
        calls.append(value)
        payload = reply(value, target=ANSWER).json()
        message = payload["message"] if api == "ollama_chat" else payload["choices"][0]["message"]
        call = message["tool_calls"][0]
        if invalid == "unknown":
            call["function"]["name"] = "transfer_to_unregistered_agent"
        elif invalid == "self":
            call["function"]["name"] = "transfer_to_" + EVIDENCE
        elif invalid == "multiple":
            message["tool_calls"].append({**call, "id": "call_second"})
        else:
            arguments = ({"task": "allowed", "evidence": []} if invalid == "extra_argument"
                         else {"task": "   "})
            call["function"]["arguments"] = (
                arguments if api == "ollama_chat" else json.dumps(arguments)
            )
        return httpx2.Response(200, json=payload, request=value)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError):
            await runner(handler).generate(selected(api), policy=POLICY)
        trace = current_agent_trace()
    assert len(calls) == 1
    assert all(span.state != "running" for span in trace.spans)
    assert REASONING_CANARY not in trace.model_dump_json()


@pytest.mark.parametrize("final_role", [EVIDENCE, REVIEW])
async def test_only_answer_role_can_return_final_answer(final_role):
    calls = []

    def handler(value):
        calls.append(value)
        if final_role == REVIEW and len(calls) == 1:
            return reply(value, target=REVIEW)
        return reply(value)

    with pytest.raises(GenerationProviderError):
        await runner(handler).generate(selected(), policy=POLICY)
    assert len(calls) == (1 if final_role == EVIDENCE else 2)


async def test_current_acl_revocation_after_handoff_prevents_recipient_http_call():
    calls = []
    checks = []

    async def authorize():
        checks.append(True)
        if len(checks) == 3:
            raise AppError("conversation_scope_changed", "Synthetic scope change", 409)

    def handler(value):
        calls.append(value)
        return reply(value, target=ANSWER if len(calls) == 1 else REVIEW)

    with pytest.raises(AppError, match="Synthetic scope change"):
        await runner(handler).generate(selected(), policy=POLICY, revalidate=authorize)
    assert len(calls) == 2 and len(checks) == 3


@pytest.mark.parametrize("cancel", [False, True])
async def test_later_handoff_partial_response_cancel_or_timeout_keeps_termination_unknown(cancel):
    stream = PartialBody()
    calls = []

    def handler(value):
        calls.append(value)
        return (reply(value, target=ANSWER) if len(calls) == 1
                else httpx2.Response(200, request=value, stream=stream))

    value = selected()
    if not cancel:
        value = replace(value, profile=replace(value.profile, timeout_seconds=0.2))
    termination = GenerationTermination()
    with capture_agent_trace(True):
        task = asyncio.create_task(tracked_generation_call(
            runner(handler).generate(value, policy=POLICY), termination,
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
    assert len(calls) == 2 and stream.closed and not termination.confirmed
    assert all(span.state != "running" for span in trace.spans)
    assert any(span.state == ("cancelled" if cancel else "failed") for span in trace.spans)


@pytest.mark.parametrize("limit", ["model", "tokens", "handoffs"])
async def test_redelegation_loop_stops_at_shared_budget_without_retry(limit):
    limits = {"max_model_calls": 3} if limit == "model" else (
        {"max_total_output_tokens": 900} if limit == "tokens" else {"max_tool_calls": 2}
    )
    calls = []

    def handler(value):
        calls.append(value)
        return reply(value, target=ANSWER if len(calls) % 2 else EVIDENCE)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError, match="orchestration_budget_exceeded"):
            await runner(handler).generate(selected(**limits), policy=POLICY)
        trace = current_agent_trace()
    assert 2 <= len(calls) <= 3
    assert all(span.state != "running" for span in trace.spans)


async def test_prior_context_call_and_reservation_share_budget_with_handoffs():
    calls = []

    def handler(value):
        calls.append(value)
        return reply(value, target=ANSWER if len(calls) == 1 else REVIEW)

    with pytest.raises(GenerationProviderError, match="orchestration_budget_exceeded"):
        await runner(handler).generate(
            selected(max_model_calls=3, max_total_output_tokens=900), policy=POLICY,
            prior_model_calls=1, prior_reserved_output_tokens=300,
        )
    assert len(calls) == 2


async def test_repeated_handoffs_keep_v6_aliases_bound_to_original_evidence_identity():
    identity = UUID(int=90003001)
    value = selected_request(identity)
    value = replace(value, profile=replace(value.profile, orchestration=OrchestrationPolicy(
        **selected().profile.orchestration.model_dump(),
    )))
    calls = []
    targets = [ANSWER, REVIEW, ANSWER]

    def handler(http_request):
        index = len(calls)
        calls.append(http_request)
        return (reply(http_request, target=targets[index]) if index < len(targets)
                else reply(http_request, content=alias_answer()))

    with capture_agent_trace(True):
        result = await runner(handler).generate(value, policy=POLICY)
        trace = current_agent_trace()
    assert len(calls) == 4
    assert result.generation.claims[0].evidence_ids == (identity,)
    models = [span for span in trace.spans if span.kind == "model"]
    assert all(span.citation_reference_map.evidence_ids == (identity,) for span in models)
    assert json.loads(models[-1].output.text)["claims"][0]["evidence_ids"] == ["e1"]
