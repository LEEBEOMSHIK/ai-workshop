import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from ai_workshop.labs.rag.deployments.domain import DeploymentCapability
from ai_workshop.labs.rag.generation.domain import GenerationStatus
from ai_workshop.labs.rag.generation.execution import (
    ProviderContextualizationResult,
    ProviderExecutionMetadata,
    ProviderGenerationResult,
    ProviderHealthResult,
)
from ai_workshop.labs.rag.generation.integrity import ConversationTurnSigner
from ai_workshop.labs.rag.highlighting.context import EvidenceBudget
from ai_workshop.labs.rag.search.schemas import ConversationTurnRequest, SearchRequest
from ai_workshop.shared.errors import AppError
from tests.unit.labs.rag.orchestration.test_agents_sdk import POLICY, request, response, runner
from tests.unit.labs.rag.search.test_generation_policy_gate import (
    ACTOR_ID,
    CONFIGURATION_ID,
    WORKSPACE_ID,
    _configuration,
    _service,
)
from tests.unit.labs.rag.search.test_provider_insufficient_evidence import (
    ActiveScopeResolver,
    OneSourceResolver,
    OneSourceRetriever,
)


def service(*, enabled=True, **limits):
    selected = request(**limits).profile
    selected = replace(selected, deployment=replace(
        selected.deployment, capabilities=frozenset({
            DeploymentCapability.STRUCTURED_OUTPUT, DeploymentCapability.CONTEXTUALIZATION,
        }),
    ))
    profile = replace(selected, evidence_budget=EvidenceBudget(8, 32, 12000),
                      orchestration=selected.orchestration if enabled else None)
    metadata = ProviderExecutionMetadata(profile.deployment.provider, profile.runtime_model,
                                        profile.deployment.id, 7, 3, 4)
    direct = SimpleNamespace(
        health=AsyncMock(return_value=ProviderHealthResult(True, profile.runtime_model, metadata)),
        contextualize=AsyncMock(return_value=ProviderContextualizationResult(
            "synthetic fact", metadata,
        )),
        generate=AsyncMock(return_value=ProviderGenerationResult(
        None, metadata,
        status=GenerationStatus.INSUFFICIENT_EVIDENCE,
    )))
    configuration = replace(_configuration(approval=None), generation_profile=profile,
                            generation_runtime=direct)
    result, _, _, audits = _service(configuration=configuration, decision=POLICY)
    result.sparse_retriever = OneSourceRetriever()
    result.scope_resolver = ActiveScopeResolver()
    result.source_resolver = OneSourceResolver()
    result.turn_signer = ConversationTurnSigner(b"synthetic-test-signing-key-32-bytes")
    return result, direct, audits


def query():
    return SearchRequest(query="synthetic fact", configuration_id=CONFIGURATION_ID,
                         workspace_ids=[WORKSPACE_ID], experimental=True, include_diagnostics=True)


@pytest.mark.parametrize("outcome", ["answered", "wrong_citation", "insufficient_evidence"])
async def test_sdk_pipeline_preserves_existing_citation_gate_and_diagnostics(outcome):
    calls = []

    def handler(value):
        calls.append(json.loads(value.content))
        if len(calls) == 1:
            return response(value, delegate=True)
        evidence_id = json.loads(calls[-1]["messages"][-1]["content"])["evidence"][0]["evidence_id"]
        return response(value, content={
            "schema_version": 2,
            "status": "insufficient_evidence" if outcome == "insufficient_evidence" else "answered",
            "claims": [] if outcome == "insufficient_evidence" else [{
                "text": "synthetic fact",
                "evidence_ids": [str(UUID(int=42)) if outcome == "wrong_citation" else evidence_id],
            }],
        })

    target, direct, audits = service()
    target.generation_orchestrator = runner(handler)
    if outcome == "wrong_citation":
        with pytest.raises(AppError, match="citation"):
            await target.search(actor_id=ACTOR_ID, request=query())
        assert audits.audits[-1].status == "failed"
    else:
        result = await target.search(actor_id=ACTOR_ID, request=query())
        assert result.generation.status.value == outcome
        assert result.diagnostics.agent_trace is not None
        if outcome == "answered":
            assert result.generation.citations[0].claim_text == "synthetic fact"
    direct.generate.assert_not_awaited()
    assert len(calls) == 2


async def test_profile_without_opt_in_keeps_direct_generation():
    target, direct, _ = service(enabled=False)
    sdk = SimpleNamespace(generate=AsyncMock(side_effect=AssertionError("Unexpected SDK call")))
    target.generation_orchestrator = sdk
    result = await target.search(actor_id=ACTOR_ID, request=query())
    assert result.generation.status is GenerationStatus.INSUFFICIENT_EVIDENCE
    direct.generate.assert_awaited_once()
    sdk.generate.assert_not_awaited()


async def test_selected_sdk_profile_without_runner_never_falls_back():
    target, direct, _ = service()
    with pytest.raises(AppError) as caught:
        await target.search(actor_id=ACTOR_ID, request=query())
    assert caught.value.code == "orchestration_not_supported"
    direct.generate.assert_not_awaited()


async def test_history_contextualization_counts_against_total_model_budget_before_call():
    target, direct, _ = service()
    target.generation_orchestrator = runner(lambda _: pytest.fail("No model call authorized"))
    selected_query = query().model_copy(update={"history": [
        ConversationTurnRequest(role="user", content="earlier synthetic question"),
    ]})
    with pytest.raises(AppError) as caught:
        await target.search(actor_id=ACTOR_ID, request=selected_query)
    assert caught.value.code == "orchestration_budget_exceeded"
    direct.contextualize.assert_not_awaited()
    direct.generate.assert_not_awaited()


async def test_history_with_three_call_budget_runs_one_context_and_two_sdk_calls():
    calls = []

    def handler(value):
        calls.append(value)
        return response(value, delegate=len(calls) == 1,
                        content={"schema_version": 2, "status": "insufficient_evidence",
                                 "claims": []})

    target, direct, audits = service(max_model_calls=3, max_total_output_tokens=900)
    target.generation_orchestrator = runner(handler)
    selected_query = query().model_copy(update={"history": [
        ConversationTurnRequest(role="user", content="earlier synthetic question"),
    ]})
    result = await target.search(actor_id=ACTOR_ID, request=selected_query)
    assert result.generation.status is GenerationStatus.INSUFFICIENT_EVIDENCE
    direct.contextualize.assert_awaited_once()
    assert len(calls) == 2
    assert audits.audits[-1].input_tokens == 67


@pytest.mark.parametrize("missing_stage", ["context", "manager", "specialist"])
async def test_combined_sdk_usage_is_unknown_if_any_call_omits_usage(missing_stage):
    calls = []

    def handler(value):
        calls.append(value)
        omitted = (missing_stage == "manager" and len(calls) == 1
                   or missing_stage == "specialist" and len(calls) == 2)
        return response(value, delegate=len(calls) == 1, usage=not omitted,
                        content={"schema_version": 2, "status": "insufficient_evidence",
                                 "claims": []})

    target, direct, audits = service(max_model_calls=3, max_total_output_tokens=900)
    if missing_stage == "context":
        prior = direct.contextualize.return_value
        direct.contextualize.return_value = replace(
            prior, execution=replace(prior.execution, input_tokens=None, output_tokens=None),
        )
    target.generation_orchestrator = runner(handler)
    selected_query = query().model_copy(update={"history": [
        ConversationTurnRequest(role="user", content="earlier synthetic question"),
    ]})
    await target.search(actor_id=ACTOR_ID, request=selected_query)
    assert len(calls) == 2
    assert audits.audits[-1].input_tokens is None
    assert audits.audits[-1].output_tokens is None
