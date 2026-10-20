"""Synthetic inputs; no model, database, or network dependencies."""

import copy
import hashlib
import json
from uuid import UUID

import pytest

from ai_workshop.labs.rag.evaluation.offline_input_diagnosis import (
    Capture,
    InstructionChange,
    prepare_comparison,
    verify_candidate,
)


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def request(company: str = "북쪽 물류", rule: str = "접수 다음 날 발송") -> dict:
    return {
        "messages": [
            {"role": "system", "content": "JSON만 반환.\n질문에 직접 답한다.\n형식 계약 유지."},
            {"role": "user", "content": encoded({
                "schema_version": 2, "question": f"{company} 발송 시점은?",
                "resolved_query": f"{company} 발송 시점은?", "history": [],
                "evidence_sources": [{"page": 1, "table_cell": None}],
                "evidence_blocks": [{"source_ref": 0, "fragments": [
                    {"evidence_id": str(UUID(int=1)),
                     "text": f"{company}: {rule}\n조건: 재고  있음",
                     "bbox": [1, 2, 3, 4], "char_range": [0, 26], "ordinal": 0},
                    {"evidence_id": str(UUID(int=2)), "text": "재고가 없으면 일정 미정",
                     "bbox": [1, 5, 3, 6], "char_range": [26, 40], "ordinal": 1},
                ]}],
                "evidence_format_notice": "원문만 인용",
            })},
        ],
        "temperature": 0, "max_tokens": 300,
        "response_format": {"type": "json_object"}, "reasoning_effort": "none",
    }


def capture(body: dict | None = None) -> Capture:
    raw = encoded(body if body is not None else request())
    return Capture(
        run_id=UUID(int=10), attempt_id=UUID(int=11), execution_id=UUID(int=12),
        kind="synthetic_fixture", request_json=raw,
        sha256=hashlib.sha256(raw.encode()).hexdigest(),
        body_bytes=len(raw.encode()), body_characters=len(raw),
        status="response_received", content_status="complete",
        model="합성 모델", model_version=1, profile_version=1, prompt_ref="fixture",
        provider="local_openai_compatible", dialect="ollama",
    )


def change() -> InstructionChange:
    return InstructionChange(
        prefix="JSON만 반환.\n", original="질문에 직접 답한다.",
        replacement="질문에 필요한 원문의 규칙과 조건을 함께 설명한다.",
        suffix="\n형식 계약 유지.",
    )


def test_prepare_preserves_original_and_separates_unexecuted_candidates() -> None:
    original = capture()
    prepared = prepare_comparison(original, change())
    a, b, c = prepared.candidates
    assert a.request_json == original.request_json
    assert a.sha256 == original.sha256
    assert {item.execution_status for item in prepared.candidates} == {"not_run"}
    assert [item.condition for item in prepared.candidates] == ["A", "B", "C"]
    assert len({item.sha256 for item in prepared.candidates}) == 3
    body_a, body_b, body_c = [json.loads(item.request_json) for item in (a, b, c)]
    assert body_a["messages"][0] == body_b["messages"][0]
    assert json.loads(body_a["messages"][1]["content"]) == json.loads(
        body_b["messages"][1]["content"]
    )
    assert body_a["messages"][1] == body_c["messages"][1]
    assert body_c["messages"][0]["content"] == (
        change().prefix + change().replacement + change().suffix
    )
    assert "재고  있음" in body_b["messages"][1]["content"]
    assert original == capture()


@pytest.mark.parametrize("company,rule", [
    ("남쪽 장비센터", "접수일로부터 9주 뒤 교체"),
    ("서쪽 도서관", "목요일에만 대여 가능"),
])
def test_no_company_or_answer_specific_transformation(company: str, rule: str) -> None:
    prepared = prepare_comparison(capture(request(company, rule)), change())
    for candidate in prepared.candidates:
        body = json.loads(candidate.request_json)
        assert rule in body["messages"][1]["content"]
        assert company not in body["messages"][0]["content"]


@pytest.mark.parametrize("field,value", [
    ("sha256", "0" * 64), ("body_bytes", 1), ("body_characters", 1),
    ("status", "prepared"), ("content_status", "omitted_size_limit"),
])
def test_incomplete_or_tampered_capture_is_rejected(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        prepare_comparison(capture().model_copy(update={field: value}), change())


@pytest.mark.parametrize("mutation", ["text", "order", "location", "reference", "duplicate"])
def test_b_rejects_any_evidence_change_even_with_updated_hash(mutation: str) -> None:
    original = capture()
    candidate = prepare_comparison(original, change()).candidates[1]
    body = json.loads(candidate.request_json)
    payload = json.loads(body["messages"][1]["content"])
    block = payload["evidence_blocks"][0]
    fragments = block["fragments"]
    if mutation == "text":
        fragments[0]["text"] = fragments[0]["text"].replace("  ", " ")
    elif mutation == "order":
        fragments.reverse()
    elif mutation == "location":
        fragments[0]["bbox"][0] = 100
    elif mutation == "reference":
        block["source_ref"] = 8
    else:
        fragments.append(copy.deepcopy(fragments[0]))
    body["messages"][1]["content"] = encoded(payload)
    raw = encoded(body)
    altered = candidate.model_copy(update={
        "request_json": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "body_bytes": len(raw.encode()),
    })
    with pytest.raises(ValueError):
        verify_candidate(original, altered, change())


def test_c_protects_everything_outside_declared_guidance() -> None:
    original = capture()
    c = prepare_comparison(original, change()).candidates[2]
    body = json.loads(c.request_json)
    body["messages"][0]["content"] += "계약 변경"
    raw = encoded(body)
    with pytest.raises(ValueError):
        verify_candidate(original, c.model_copy(update={
            "request_json": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "body_bytes": len(raw.encode()),
        }), change())


def test_unknown_fields_and_duplicate_json_keys_are_rejected() -> None:
    body = request()
    body["authorization"] = "not-a-real-secret"
    with pytest.raises(ValueError):
        prepare_comparison(capture(body), change())
    original = capture()
    raw = original.request_json[:-1] + ',"temperature":1}'
    with pytest.raises(ValueError):
        prepare_comparison(original.model_copy(update={
            "request_json": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "body_bytes": len(raw.encode()), "body_characters": len(raw),
        }), change())


def test_answer_material_is_not_an_input_to_candidate_builder() -> None:
    body = request()
    user = json.loads(body["messages"][1]["content"])
    user["expected_answer"] = "평가용 정답"
    body["messages"][1]["content"] = encoded(user)
    with pytest.raises(ValueError):
        prepare_comparison(capture(body), change())


def test_mismatched_or_noop_guidance_is_rejected() -> None:
    for patch in (
        change().model_copy(update={"prefix": "잘못된 경계"}),
        change().model_copy(update={"replacement": change().original}),
        change().model_copy(update={"replacement": "??? ?????? ???."}),
    ):
        with pytest.raises(ValueError):
            prepare_comparison(capture(), patch)


def test_b_preserves_json_string_escapes_and_number_lexemes() -> None:
    body = request()
    user = body["messages"][1]["content"].replace("북쪽", r"\ubd81\ucabd")
    user = user.replace('"bbox":[1,2,3,4]', '"bbox":[1e0,2.00,3,4]')
    body["messages"][1]["content"] = user
    prepared = prepare_comparison(capture(body), change())
    new = json.loads(prepared.candidates[1].request_json)["messages"][1]["content"]
    assert r"\ubd81\ucabd" in new
    assert "1e0" in new and "2.00" in new


@pytest.mark.parametrize("field,value", [
    ("provider", "remote_openai"), ("dialect", "unknown"), ("prompt_ref", "unsupported"),
])
def test_actual_capture_rejects_unsupported_provenance(field: str, value: str) -> None:
    original = capture().model_copy(update={
        "kind": "actual_capture", "provider": "local_openai_compatible", "dialect": "ollama",
        "prompt_ref": "rag-answer-v5", field: value,
    })
    with pytest.raises(ValueError):
        prepare_comparison(original, change())


@pytest.mark.parametrize("field", ["schema_version", "history", "resolved_query",
                                  "evidence_format_notice"])
def test_missing_required_user_fields_are_rejected(field: str) -> None:
    body = request()
    payload = json.loads(body["messages"][1]["content"])
    del payload[field]
    body["messages"][1]["content"] = encoded(payload)
    with pytest.raises(ValueError):
        prepare_comparison(capture(body), change())


@pytest.mark.parametrize("field,value", [
    ("schema_version", 999), ("schema_version", True), ("history", {}),
    ("resolved_query", 1), ("evidence_format_notice", []),
])
def test_invalid_required_user_fields_are_rejected(field: str, value: object) -> None:
    body = request()
    payload = json.loads(body["messages"][1]["content"])
    payload[field] = value
    body["messages"][1]["content"] = encoded(payload)
    with pytest.raises(ValueError):
        prepare_comparison(capture(body), change())
