import json
from dataclasses import replace
from uuid import UUID

import httpx2
import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.executions.agent_trace import capture_agent_trace, current_agent_trace
from ai_workshop.labs.rag.generation.domain import GenerationStatus
from ai_workshop.labs.rag.generation.openai_compatible import http_answer_instructions
from ai_workshop.labs.rag.models.orchestration_policy import OrchestrationPolicy
from tests.unit.labs.rag.orchestration.test_agents_sdk import (
    POLICY,
    answer,
    evidence,
    request,
    runner,
)
from tests.unit.labs.rag.orchestration.test_reference_packing_independent import selected_request


def autonomous_request(api="openai_chat_completions", **limits):
    return request(version=2, dispatch_mode="autonomous_handoffs", local_http_api=api,
                   **({"max_model_calls": 6, "max_tool_calls": 5,
                       "max_total_output_tokens": 1800} | limits))


def handoff_response(value, target=None, task="원문 조건을 확인하고 답변하세요.", content=None):
    body = json.loads(value.content)
    native = value.url.path.endswith("/api/chat")
    message = {"role": "assistant", "content": json.dumps(content or answer(), ensure_ascii=False)}
    if target:
        message = {"role": "assistant", "content": "", "tool_calls": [{
            "id": "synthetic_handoff", "type": "function", "function": {
                "name": f"transfer_to_{target}",
                "arguments": {"task": task} if native else json.dumps({"task": task}),
            },
        }]}
    if native:
        return httpx2.Response(200, json={"model": body["model"], "message": message,
            "done": True, "done_reason": "stop", "prompt_eval_count": 30, "eval_count": 15})
    return httpx2.Response(200, json={"id": "synthetic", "object": "chat.completion",
        "created": 1, "model": body["model"], "choices": [{"index": 0, "message": message,
        "finish_reason": "tool_calls" if target else "stop"}],
        "usage": {"prompt_tokens": 30, "completion_tokens": 15, "total_tokens": 45}})


@pytest.mark.parametrize("api", ["openai_chat_completions", "ollama_chat"])
@pytest.mark.parametrize("route", [
    ["answer_specialist", None],
    ["answer_specialist", "review_specialist", "evidence_specialist",
     "answer_specialist", None],
])
async def test_real_sdk_dynamic_roundtrip_keeps_original_input_and_distinct_spans(api, route):
    calls = []
    checks = []

    async def revalidate():
        checks.append(True)

    def handler(value):
        calls.append(json.loads(value.content))
        return handoff_response(value, route[len(calls) - 1], task=f"작업 {len(calls)}")

    with capture_agent_trace(True):
        result = await runner(handler).generate(autonomous_request(api), policy=POLICY,
                                                revalidate=revalidate)
        trace = current_agent_trace()
    assert result.status is GenerationStatus.ANSWERED
    assert result.generation.claims[0].text == evidence().text
    assert len(calls) == len(checks) == len(route)
    agents = [span for span in trace.spans if span.kind == "agent"]
    assert [span.name for span in agents] == ["evidence_specialist", *route[:-1]]
    assert len({span.id for span in agents}) == len(agents)
    assert trace.observation_complete
    assert all(span.state == "completed" for span in trace.spans)
    handoffs = [span for span in trace.spans if span.kind == "delegation"]
    assert len(handoffs) == len(route) - 1
    assert all(span.delegation_mode == "handoff" for span in handoffs)
    for index, call in enumerate(calls):
        assert len(call["messages"]) == 2
        data = json.loads(call["messages"][1]["content"])
        assert data["question"] == request().question
        assert evidence().text in call["messages"][1]["content"]
        if index:
            assert data["delegated_task"] == f"작업 {index}"
        assert len(call["tools"]) == 2


@pytest.mark.parametrize("overrides", [
    {"version": 1, "dispatch_mode": "autonomous_handoffs"},
    {"version": 2, "dispatch_mode": "manager_delegation"},
    {"version": 2, "dispatch_mode": "autonomous_handoffs", "max_model_calls": 9},
    {"version": 2, "dispatch_mode": "autonomous_handoffs", "max_tool_calls": 8},
])
def test_policy_rejects_incompatible_versions_and_unbounded_limits(overrides):
    raw = dict(engine="openai_agents", version=2, dispatch_mode="autonomous_handoffs",
               max_model_calls=6, max_tool_calls=5, max_total_output_tokens=1800)
    with pytest.raises(ValidationError):
        OrchestrationPolicy(**(raw | overrides))


@pytest.mark.parametrize("api", ["openai_chat_completions", "ollama_chat"])
@pytest.mark.parametrize("reference_input", [False, True])
async def test_routing_roles_do_not_receive_final_answer_only_contract(api, reference_input):
    value = autonomous_request(api)
    output = answer()
    if reference_input:
        selected = selected_request(UUID(int=90003001))
        value = replace(selected, profile=replace(
            selected.profile, orchestration=value.profile.orchestration,
        ))
        output["claims"][0]["text"] = value.evidence[0].text
        output["claims"][0]["evidence_ids"] = ["e1"]
    calls = []
    route = ["review_specialist", "answer_specialist", "evidence_specialist",
             "answer_specialist", None]

    def handler(wire_request):
        calls.append(json.loads(wire_request.content))
        return handoff_response(wire_request, route[len(calls) - 1], content=output)

    result = await runner(handler).generate(value, policy=POLICY)
    assert result.status is GenerationStatus.ANSWERED
    assert result.generation.claims[0].evidence_ids == (value.evidence[0].evidence_id,)
    for index, role in enumerate(["evidence_specialist", *route[:-1]]):
        instructions = calls[index]["messages"][0]["content"]
        if role == "answer_specialist":
            assert http_answer_instructions(value.profile, dialect="ollama") in instructions
        else:
            assert '"schema_version"' not in instructions
            assert "JSON만 반환" not in instructions
            assert "transfer_to_" in instructions and "task" in instructions
        assert "작업 데이터" in instructions
        assert "원문의 조건과 예외를 보존" in instructions
