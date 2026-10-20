import json
from dataclasses import replace
from hashlib import sha256
from unittest.mock import AsyncMock

import pytest

from ai_workshop.labs.rag.generation.evidence_payload import evidence_payload
from ai_workshop.labs.rag.generation.execution import GenerationProviderError
from ai_workshop.labs.rag.generation.input_inspection import (
    CAPTURE_LIMIT_CHARACTERS,
    capture_generation_input,
    current_input_inspection,
    record_generation_input,
    record_generation_response,
)
from tests.unit.labs.rag.generation.test_http_evidence_groups import restore
from tests.unit.labs.rag.generation.test_source_reading import request_for, stored_evidence
from tests.unit.labs.rag.generation.test_source_reading_mock import (
    MockBoundaryRuntime,
    complete_without_io,
)


def record(body: dict[str, object]) -> None:
    record_generation_input(body, provider="local_openai_compatible", dialect="ollama",
                            prompt_ref="rag-answer-v3", profile_version=3, evidence_budget=None,
                            model_name="Display model", model_version=1)


def test_capture_is_opt_in_isolated_and_detached() -> None:
    body: dict[str, object] = {"model": "synthetic", "messages": [
        {"role": "system", "content": "Final instruction"},
        {"role": "user", "content": json.dumps({"evidence": [
            {"evidence_id": "synthetic-id", "text": "T+4; holidays excluded"}]})},
    ], "max_tokens": 128, "Authorization": "must-never-copy", "endpoint": "private"}
    record(body)
    assert current_input_inspection() is None
    with capture_generation_input(True):
        record(body)
        first = current_input_inspection()
        assert first is not None and first.status == "prepared"
        assert first.request_json is not None
        assert "must-never-copy" not in first.request_json
        assert "endpoint" not in first.request_json
        body["messages"] = []
        assert "holidays excluded" in first.request_json
        assert first.sha256 == sha256(first.request_json.encode()).hexdigest()
        with capture_generation_input(False):
            assert current_input_inspection() is None
            record_generation_response()
        assert current_input_inspection() == first
        record_generation_response()
        assert current_input_inspection().status == "response_received"
    assert current_input_inspection() is None


def test_oversize_omits_whole_content_without_altering_request() -> None:
    body: dict[str, object] = {"model": "synthetic", "max_tokens": 128,
                              "messages": [{"role": "user",
                                            "content": "가" * CAPTURE_LIMIT_CHARACTERS}]}
    with capture_generation_input(True):
        record(body)
        result = current_input_inspection()
        assert result is not None
        assert result.request_json is None
        assert result.content_status == "omitted_size_limit"
        assert result.body_bytes > result.body_characters > CAPTURE_LIMIT_CHARACTERS
        assert result.provider_truncation == "unknown"
    assert len(body["messages"][0]["content"]) == CAPTURE_LIMIT_CHARACTERS


def test_failed_request_does_not_claim_response_and_context_resets() -> None:
    try:
        with capture_generation_input(True):
            record({"model": "synthetic", "max_tokens": 1, "messages": []})
            raise ValueError("synthetic failure")
    except ValueError:
        pass
    assert current_input_inspection() is None


@pytest.mark.parametrize("reference", ["rag-answer-v3", "rag-answer-v4"])
@pytest.mark.parametrize("dialect", ["openai", "ollama"])
def test_capture_matches_final_adapter_body_and_preserves_stored_sources(reference, dialect):
    items = stored_evidence()
    request = request_for(items, reference=reference, question="합성 상품 지급 조건은?")
    runtime = MockBoundaryRuntime(request, {
        "schema_version": 2, "status": "insufficient_evidence", "claims": [],
    })
    runtime.dialect = dialect
    with capture_generation_input(True):
        complete_without_io(runtime, request)
        result = current_input_inspection()
        assert result is not None and result.request_json is not None
        assert result.status == "response_received"
        assert result.prompt_ref == reference and result.dialect == dialect
        assert result.evidence_budget == request.profile.evidence_budget
        body = json.loads(result.request_json)
        assert body == {k: v for k, v in runtime.sent[0].items() if k != "model"}
        assert "model" not in body
        assert result.model == request.profile.model_name
        assert request.profile.runtime_model not in result.request_json
        assert "Return only JSON" in body["messages"][0]["content"]
        if dialect == "ollama":
            assert body["response_format"]["type"] == "json_schema"
        payload = json.loads(body["messages"][1]["content"])
        assert restore(payload) == evidence_payload(items, contextual=True)
        assert payload["question"] == request.question
        assert {row["evidence_id"] for row in payload["evidence"]} == {
            str(item.evidence_id) for item in items}
    # Collection is observational: the exact generated request remains unchanged.
    uncaptured = MockBoundaryRuntime(request, runtime.answer)
    uncaptured.dialect = dialect
    complete_without_io(uncaptured, request)
    assert uncaptured.sent == runtime.sent
    assert current_input_inspection() is None


def test_contextualization_does_not_replace_answer_snapshot():
    request = request_for(stored_evidence())
    runtime = MockBoundaryRuntime(request, {
        "schema_version": 2, "status": "insufficient_evidence", "claims": [],
    })
    with capture_generation_input(True):
        complete_without_io(runtime, request)
        original = current_input_inspection()
        operation = runtime._chat_completion(
            profile=replace(request.profile, prompt_ref="rag-contextualize-v1"),
            system_prompt="synthetic rewrite", user_content="synthetic", contextualize=True,
        )
        with pytest.raises(StopIteration):
            operation.send(None)
        operation.close()
        assert current_input_inspection() == original


def test_adapter_failure_never_claims_response_received(monkeypatch):
    request = request_for(stored_evidence())
    runtime = MockBoundaryRuntime(request, {})
    monkeypatch.setattr(runtime, "_request_json", AsyncMock(
        side_effect=GenerationProviderError("provider_unavailable", retryable=False)))
    with capture_generation_input(True):
        operation = runtime.generate(request)
        try:
            with pytest.raises(GenerationProviderError):
                operation.send(None)
        finally:
            operation.close()
        inspection = current_input_inspection()
        assert inspection is not None and inspection.status == "prepared"
    assert current_input_inspection() is None
