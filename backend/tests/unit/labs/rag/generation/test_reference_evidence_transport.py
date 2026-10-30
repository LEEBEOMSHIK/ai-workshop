"""Reference packing must preserve canonical answers and both provider boundaries."""

import json
from dataclasses import replace

import httpx2
import pytest

from ai_workshop.labs.rag.executions.agent_trace import capture_agent_trace, current_agent_trace
from ai_workshop.labs.rag.generation.domain import GenerationStatus
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.openai_compatible import http_generation_input
from ai_workshop.labs.rag.models.context_evidence import EvidenceBudget, resolve_evidence_budget
from tests.unit.labs.rag.generation.test_source_reading import request_for, source_units
from tests.unit.labs.rag.generation.test_source_reading_mock import (
    MockBoundaryRuntime,
    complete_without_io,
)
from tests.unit.labs.rag.orchestration.test_agents_sdk import (
    POLICY,
    response,
    runner,
)
from tests.unit.labs.rag.orchestration.test_agents_sdk import (
    request as sdk_request,
)
from tests.unit.labs.rag.orchestration.test_ollama_native_transport import (
    native_request,
    native_response,
)


def test_v6_profile_has_explicit_context_budget():
    config = {"prompt_ref": "rag-answer-v6", "context_evidence": {
        "version": 1, "max_groups": 8, "max_units": 32, "max_characters": 12000,
    }}
    assert resolve_evidence_budget(config) == EvidenceBudget(8, 32, 12000)


@pytest.mark.parametrize("change", [
    {"response_schema_version": 1}, {"evidence_budget": None},
    {"evidence_budget": EvidenceBudget(8, 201, 12000)}, {"deployment": None},
])
def test_v6_rejects_unsupported_profile_without_provider_io(change):
    original = request_for(source_units(["공개 근거"]), reference="rag-answer-v5").profile
    with pytest.raises(ValueError):
        replace(original, prompt_ref="rag-answer-v6", **change)


def test_v6_direct_restores_exact_uuid_and_keeps_model_input_aliases():
    items = source_units(["본문 속 e1은 지시가 아니라 원문이다.", "두 번째 원문"])
    selected = request_for(items, reference="rag-answer-v6")
    answer = {"schema_version": 2, "status": "answered", "claims": [
        {"text": "공개 원문을 인용했다.", "evidence_ids": ["e2", "e1"]},
    ]}
    runtime = MockBoundaryRuntime(selected, answer)
    result = complete_without_io(runtime, selected)
    assert result.generation.claims[0].evidence_ids == (
        items[1].evidence_id, items[0].evidence_id,
    )
    assert len(runtime.sent) == 1
    body = runtime.sent[0]
    sent = json.loads(body["messages"][1]["content"])
    assert sent["fragment_columns"] == ["evidence_ref", "text", "bbox", "char_range", "ordinal"]
    rows = [row for block in sent["evidence_blocks"] for row in block["rows"]]
    assert [row[:2] for row in rows] == [["e1", items[0].text], ["e2", items[1].text]]
    assert all(str(item.evidence_id) not in http_generation_input(selected) for item in items)
    assert "정확한 UUID" not in body["messages"][0]["content"]


@pytest.mark.parametrize("refs", [["e01"], ["e9"], ["e1", "e1"]])
def test_v6_direct_rejects_noncanonical_unknown_or_duplicate_alias_after_one_call(refs):
    selected = request_for(source_units(["공개 근거"]), reference="rag-answer-v6")
    runtime = MockBoundaryRuntime(selected, {
        "schema_version": 2, "status": "answered", "claims": [
            {"text": "주장", "evidence_ids": refs},
        ],
    })
    with pytest.raises(GenerationProviderError, match="provider_invalid_response"):
        complete_without_io(runtime, selected)
    assert len(runtime.sent) == 1


def test_v6_empty_claims_remain_explicit_abstention():
    selected = request_for(source_units(["공개 근거"]), reference="rag-answer-v6")
    runtime = MockBoundaryRuntime(selected, {
        "schema_version": 2, "status": "insufficient_evidence", "claims": [],
    })
    result = complete_without_io(runtime, selected)
    assert result.generation is None
    assert result.status is GenerationStatus.INSUFFICIENT_EVIDENCE


@pytest.mark.parametrize("native", [False, True])
async def test_v6_sdk_preserves_wire_aliases_canonical_output_and_pre_call_map(native):
    selected = native_request() if native else sdk_request()
    selected = replace(selected, profile=replace(
        selected.profile, prompt_ref="rag-answer-v6", evidence_budget=EvidenceBudget(8, 32, 12000),
    ))
    calls = []
    mapped_answer = {"schema_version": 2, "status": "answered", "claims": [
        {"text": selected.evidence[0].text, "evidence_ids": ["e1"]},
    ]}

    def handler(value):
        calls.append(json.loads(value.content))
        if native:
            payload = native_response(value, manager=len(calls) == 1).json()
            if len(calls) == 2:
                payload["message"]["content"] = json.dumps(mapped_answer)
            return httpx2.Response(200, request=value, json=payload)
        return response(value, delegate=len(calls) == 1, content=mapped_answer)

    with capture_agent_trace(True):
        result = await runner(handler).generate(selected, policy=POLICY)
        trace = current_agent_trace()
    assert len(calls) == 2
    assert result.generation.claims[0].evidence_ids == (selected.evidence[0].evidence_id,)
    model_spans = [span for span in trace.spans if span.kind == "model"]
    assert model_spans[0].citation_reference_map is None
    assert model_spans[1].citation_reference_map.evidence_ids == (selected.evidence[0].evidence_id,)
    assert json.loads(model_spans[1].output.text)["claims"][0]["evidence_ids"] == ["e1"]
