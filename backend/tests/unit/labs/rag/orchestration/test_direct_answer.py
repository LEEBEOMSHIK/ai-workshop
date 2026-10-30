"""Actual SDK dispatch contracts using public synthetic data and mock HTTP only."""

import asyncio
import json
from dataclasses import replace

import httpx2
import pytest
from pydantic import ValidationError

from ai_workshop.labs.rag.executions.agent_trace import capture_agent_trace, current_agent_trace
from ai_workshop.labs.rag.generation.domain import GenerationStatus
from ai_workshop.labs.rag.generation.execution import (
    GenerationProviderError,
    GenerationTermination,
    tracked_generation_call,
)
from ai_workshop.labs.rag.generation.openai_compatible import http_generation_input
from ai_workshop.labs.rag.models.orchestration_policy import (
    OrchestrationPolicy,
    resolve_orchestration_policy,
)
from ai_workshop.labs.rag.orchestration.budget import require_generation_budget
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.generation.test_source_reading import request_for, stored_evidence
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, response, runner
from tests.unit.labs.rag.orchestration.test_ollama_native_transport import native_response
from tests.unit.labs.rag.orchestration.test_policy import configuration


def selected_request(mode="direct_answer", *, native=False, **limits):
    selected = request_for(stored_evidence(), reference="rag-answer-v6")
    policy = OrchestrationPolicy(**configuration(
        dispatch_mode=mode,
        local_http_api="ollama_chat" if native else "openai_chat_completions",
        **limits,
    ))
    return replace(selected, profile=replace(selected.profile, orchestration=policy))


def answer():
    return {"schema_version": 2, "status": "answered", "claims": [
        {"text": "공개 근거의 일반 기준을 보존한다.", "evidence_ids": ["e2", "e1"]},
    ]}


def provider_response(value, selected, *, native=False, manager=False, content=None):
    payload = (native_response(value, manager=manager).json() if native
               else response(value, delegate=manager, content=content or answer()).json())
    message = payload["message"] if native else payload["choices"][0]["message"]
    if manager:
        function = message["tool_calls"][0]["function"]
        function["arguments"] = ({"task": selected.question} if native
                                 else json.dumps({"task": selected.question}))
    else:
        message["content"] = json.dumps(content or answer())
    return httpx2.Response(200, request=value, json=payload)


def test_omitted_dispatch_mode_preserves_manager_default_and_raw_config():
    config = {"orchestration": configuration()}
    policy = resolve_orchestration_policy(config)
    assert policy.dispatch_mode == "manager_delegation"
    assert "dispatch_mode" not in config["orchestration"]


@pytest.mark.parametrize("mode", ["manager_delegation", "direct_answer"])
def test_explicit_dispatch_mode_roundtrips_and_is_frozen(mode):
    policy = OrchestrationPolicy(**configuration(dispatch_mode=mode))
    assert OrchestrationPolicy.model_validate_json(policy.model_dump_json()) == policy
    with pytest.raises(ValidationError):
        policy.dispatch_mode = "direct_answer"


@pytest.mark.parametrize("mode", [None, True, 1, "", "direct", "DIRECT_ANSWER", {}])
def test_unknown_or_coerced_dispatch_mode_is_rejected(mode):
    with pytest.raises(ValidationError):
        OrchestrationPolicy(**configuration(dispatch_mode=mode))


@pytest.mark.parametrize("prior,calls,tokens", [(0, 1, 300), (1, 2, 600)])
def test_direct_budget_reserves_one_generation_and_prior_context(prior, calls, tokens):
    selected = selected_request(max_model_calls=calls, max_total_output_tokens=tokens)
    require_generation_budget(selected.profile, prior_model_calls=prior,
                              prior_reserved_output_tokens=prior * 300)


@pytest.mark.parametrize("mode,prior,calls,tokens", [
    ("direct_answer", 0, 1, 299), ("direct_answer", 1, 1, 600),
    ("direct_answer", 1, 2, 599), ("manager_delegation", 0, 1, 600),
    ("manager_delegation", 1, 2, 900), ("manager_delegation", 1, 3, 899),
])
def test_budget_rejects_insufficient_total_for_the_selected_dispatch(mode, prior, calls, tokens):
    selected = selected_request(mode, max_model_calls=calls, max_total_output_tokens=tokens)
    with pytest.raises(GenerationProviderError, match="orchestration_budget_exceeded"):
        require_generation_budget(selected.profile, prior_model_calls=prior,
                                  prior_reserved_output_tokens=prior * 300)


@pytest.mark.parametrize("native", [False, True])
async def test_direct_sdk_one_call_two_spans_matches_delegated_specialist_wire(native):
    observed = {}
    results = {}
    for mode in ("manager_delegation", "direct_answer"):
        selected = selected_request(mode, native=native)
        calls, checks = [], []

        async def authorize(checks=checks):
            checks.append(True)

        def handler(value, calls=calls, selected=selected, mode=mode):
            calls.append(bytes(value.content))
            return provider_response(value, selected, native=native,
                                     manager=mode == "manager_delegation" and len(calls) == 1)

        termination = GenerationTermination()
        with capture_agent_trace(True):
            results[mode] = await tracked_generation_call(runner(handler).generate(
                selected, policy=POLICY, revalidate=authorize,
            ), termination)
            trace = current_agent_trace()
        assert trace is not None and trace.observation_complete
        assert termination.confirmed
        assert all(span.state == "completed" for span in trace.spans)
        assert len(calls) == len(checks) == (1 if mode == "direct_answer" else 2)
        assert len(trace.spans) == (2 if mode == "direct_answer" else 5)
        specialist = next(span for span in trace.spans if span.name == "answer_specialist")
        model = [span for span in trace.spans if span.kind == "model"][-1]
        assert model.parent_id == specialist.id
        assert model.citation_reference_map.evidence_ids == tuple(
            item.evidence_id for item in selected.evidence
        )
        if mode == "direct_answer":
            assert specialist.parent_id is None
            assert [span.kind for span in trace.spans] == ["agent", "model"]
        actual_input = json.loads(json.loads(calls[-1])["messages"][-1]["content"])
        expected_input = json.loads(http_generation_input(selected))
        expected_input["delegated_task"] = selected.question
        assert actual_input == expected_input
        observed[mode] = calls[-1]
    assert observed["direct_answer"] == observed["manager_delegation"]
    assert results["direct_answer"].generation == results["manager_delegation"].generation
    assert results["direct_answer"].generation.claims[0].evidence_ids == (
        selected.evidence[1].evidence_id, selected.evidence[0].evidence_id,
    )


async def test_direct_original_long_question_does_not_use_delegation_argument_limit():
    selected = replace(selected_request(max_model_calls=1, max_total_output_tokens=300),
                       question="원질문 " * 1100)
    calls = []

    def handler(value):
        calls.append(json.loads(value.content))
        return provider_response(value, selected)

    await runner(handler).generate(selected, policy=POLICY)
    assert len(calls) == 1
    assert json.loads(calls[0]["messages"][-1]["content"])["delegated_task"] == selected.question


async def test_direct_abstention_is_not_reinterpreted_as_invalid_delegation():
    selected = selected_request()
    result = await runner(lambda value: provider_response(value, selected, content={
        "schema_version": 2, "status": "insufficient_evidence", "claims": [],
    })).generate(selected, policy=POLICY)
    assert result.status is GenerationStatus.INSUFFICIENT_EVIDENCE
    assert result.generation is None


@pytest.mark.parametrize("refs", [["e0"], ["e01"], ["e1", "e1"], ["e999"]])
async def test_direct_invalid_citation_fails_after_one_call_without_fallback(refs):
    selected, calls = selected_request(), []

    def handler(value):
        calls.append(value)
        content = answer()
        content["claims"][0]["evidence_ids"] = refs
        return provider_response(value, selected, content=content)

    with capture_agent_trace(True):
        with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
            await runner(handler).generate(selected, policy=POLICY)
        trace = current_agent_trace()
    assert len(calls) == 1
    assert len(trace.spans) == 2
    assert trace.spans[-1].citation_reference_map is not None


async def test_direct_acl_failure_prevents_http_and_preserves_application_error():
    async def denied():
        raise AppError("source_access_denied", "Access revoked.", 403)

    with pytest.raises(AppError, match="Access revoked"):
        await runner(lambda _: pytest.fail("No HTTP after denied ACL")).generate(
            selected_request(), policy=POLICY, revalidate=denied,
        )


@pytest.mark.parametrize("cancel", [False, True])
async def test_direct_timeout_or_cancel_keeps_unconfirmed_termination_and_real_spans(cancel):
    entered = asyncio.Event()
    selected = selected_request()
    if not cancel:
        selected = replace(selected, profile=replace(selected.profile, timeout_seconds=0.05))

    async def handler(_value):
        entered.set()
        await asyncio.Event().wait()

    termination = GenerationTermination()
    with capture_agent_trace(True):
        if cancel:
            task = asyncio.create_task(tracked_generation_call(
                runner(handler).generate(selected, policy=POLICY), termination,
            ))
            await asyncio.wait_for(entered.wait(), 5)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(GenerationProviderError, match="provider_timeout"):
                await tracked_generation_call(
                    runner(handler).generate(selected, policy=POLICY), termination,
                )
        trace = current_agent_trace()
    assert entered.is_set() and not termination.confirmed
    assert len(trace.spans) == 2
    assert {span.state for span in trace.spans} == {"cancelled" if cancel else "failed"}
