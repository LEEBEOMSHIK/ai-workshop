"""Actual adapter/capture boundaries with authored responses, never model calls."""

import json
from typing import Any

import pytest

from ai_workshop.labs.rag.evaluation.offline_rubric import Answer, Claim, Evidence, Rubric, assess
from ai_workshop.labs.rag.generation.domain import GenerationStatus
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.input_inspection import (
    capture_generation_input,
    current_input_inspection,
)
from ai_workshop.labs.rag.generation.prompts import prompt_reference_version
from tests.unit.labs.rag.generation.test_compact_evidence import REF
from tests.unit.labs.rag.generation.test_source_reading import (
    FIXTURE,
    fixture,
    request_for,
    source_units,
    stored_evidence,
)
from tests.unit.labs.rag.generation.test_source_reading_mock import (
    MockBoundaryRuntime,
    complete_without_io,
)


@pytest.mark.parametrize("schema", [1, 2])
@pytest.mark.parametrize("scenario", fixture()["scenarios"], ids=lambda c: c["name"])
def test_compact_request_preserves_answer_contract_and_captured_message_bytes(
    schema: int, scenario: dict[str, Any],
) -> None:
    items = source_units(scenario["texts"])
    request = request_for(items, reference=REF, schema=schema, question=scenario["question"])
    text = scenario["mock_claim"]
    claims = [{"text": text, "evidence_ids": [str(e.evidence_id) for e in items]}] if text else []
    answer = {"schema_version": schema, "claims": claims}
    if schema == 2:
        answer["status"] = "answered" if claims else "insufficient_evidence"
    runtime = MockBoundaryRuntime(request, answer)
    with capture_generation_input(True):
        result = complete_without_io(runtime, request)
        inspection = current_input_inspection()
        assert inspection is not None and inspection.request_json is not None
        assert inspection.status == "response_received"
        captured = json.loads(inspection.request_json)
    assert current_input_inspection() is None
    assert len(runtime.sent) == 1
    body = runtime.sent[0]
    assert captured["messages"] == body["messages"]
    assert "model" not in captured
    user = json.loads(body["messages"][1]["content"])
    assert user["question"] == scenario["question"]
    assert [f["text"] for b in user["evidence_blocks"] for f in b["fragments"]] == scenario["texts"]
    assert body["max_tokens"] == request.profile.max_output_tokens
    assert prompt_reference_version(REF) == 5
    if text:
        assert result.generation is not None
        assert result.generation.schema_version == schema
        assert result.generation.claims[0].text == text
        assert result.generation.claims[0].evidence_ids == tuple(e.evidence_id for e in items)
    else:
        assert result.status is GenerationStatus.INSUFFICIENT_EVIDENCE
        assert result.generation is None


@pytest.mark.parametrize("invalid_id", ["0", "source_ref:0", "block:0"])
def test_source_references_and_block_numbers_are_not_accepted_as_citations(invalid_id: str) -> None:
    request = request_for(source_units(["A supported statement."]), reference=REF)
    runtime = MockBoundaryRuntime(request, {
        "schema_version": 2, "status": "answered",
        "claims": [{"text": "A supported statement.", "evidence_ids": [invalid_id]}],
    })
    with pytest.raises(GenerationProviderError):
        complete_without_io(runtime, request)
    # Must reach response validation rather than failing to load an unregistered prompt.
    assert len(runtime.sent) == 1


def test_v5_does_not_repair_or_relabel_the_saved_incorrect_answer() -> None:
    original = json.loads(
        (FIXTURE.parent / "offline_payment_rubric.json").read_text(encoding="utf-8")
    )
    observed = original["observed_answer"]
    request = request_for(stored_evidence(), reference=REF)
    runtime = MockBoundaryRuntime(request, {
        "schema_version": 2, "status": "answered", "claims": observed["claims"],
    })
    result = complete_without_io(runtime, request)
    assert result.generation is not None
    answer = Answer(
        status="answered", answer=" ".join(c.text for c in result.generation.claims),
        claims=tuple(
            Claim(text=c.text, evidence_ids=c.evidence_ids) for c in result.generation.claims
        ),
        citation_validation="passed",
    )
    assert answer.model_dump(mode="json") == observed
    report = assess(answer, Rubric.model_validate(original["rubric"]),
                    tuple(Evidence.model_validate(e) for e in original["evidence"]))
    assert report.status == "failed"
    assert {f.code for f in report.findings} == {
        "required_rule_missing", "example_condition_missing", "example_support_incomplete",
    }
    assert len(runtime.sent) == 1
