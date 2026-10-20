"""Artifact joins, review separation, and safe standalone rendering."""

import copy
import hashlib
import json
from pathlib import Path
from uuid import UUID

import pytest

from ai_workshop.labs.rag.evaluation.generative import (
    ClaimCitation,
    GenerativeObservation,
    PrivateGenerativeResult,
)
from ai_workshop.labs.rag.evaluation.offline_input_artifacts import load_records
from ai_workshop.labs.rag.evaluation.offline_input_diagnosis import InstructionChange
from ai_workshop.labs.rag.evaluation.offline_input_report import build_report, write_report
from ai_workshop.labs.rag.evaluation.offline_rubric import Evidence, Rubric, Rule


def artifacts() -> tuple[dict, dict, InstructionChange]:
    eid, execution, attempt, case, run = [UUID(int=i) for i in range(1, 6)]
    question = "가상 도서관 대여 조건은?"
    text = "성인 회원에게 2주 동안 대여한다."
    payload = {
        "question": question, "schema_version": 2, "resolved_query": question, "history": [],
        "evidence_format_notice": "source_ref 안내",
        "evidence_sources": [{"page": 3, "source_kind": "pdf_page", "source_part": None,
                              "section_path": [], "table_cell": None}],
        "evidence_blocks": [{"source_ref": 0, "fragments": [{
            "evidence_id": str(eid), "text": text, "bbox": None,
            "char_range": [0, len(text)], "ordinal": 0,
        }]}],
    }
    patch = InstructionChange(prefix="출력 계약.\n", original="질문에 답한다.",
                              replacement="적용 조건을 포함해 답한다.", suffix="\n형식 안내.")
    body = {"messages": [
        {"role": "system", "content": patch.prefix + patch.original + patch.suffix},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ], "max_tokens": 256, "temperature": 0, "response_format": {"type": "json_object"}}
    raw = json.dumps(body, ensure_ascii=False)
    inspection = {
        "request_json": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest(),
        "body_bytes": len(raw.encode()), "body_characters": len(raw),
        "status": "response_received", "content_status": "complete", "model": "합성 모델",
        "model_version": 2, "profile_version": 3, "prompt_ref": "synthetic-profile",
        "provider": "local_openai_compatible", "dialect": "ollama",
    }
    captures = {"run_id": str(run), "attempts": [{
        "attempt_id": str(attempt), "execution_id": str(execution),
        "question": question, "inspection": inspection,
    }]}
    result = PrivateGenerativeResult(
        observation=GenerativeObservation(execution_id=execution, generation_status="answered",
                                         selected_evidence_ids=(eid,), cited_evidence_ids=(eid,),
                                         citation_valid=True),
        answer="2주 동안 대여한다.",
        citations=(ClaimCitation(claim_index=0, claim_text="2주 동안 대여한다.",
                                 evidence_ids=(eid,)),),
        evidence=({"excerpt": text, "source": {"evidence_unit_id": str(eid),
                   "title": "합성 도서관 안내", "section_path": [], "location": {
                       "page": 3, "bbox": None, "char_start": 0, "char_end": len(text),
                       "source_kind": "pdf_page", "source_part": None, "table_cell": None,
                   }}},),
    )
    results = {"run": {"id": str(run)}, "attempts": [{
        "id": str(attempt), "execution_id": str(execution), "case_id": str(case),
        "status": "completed", "query": question, "repetition": 0,
        "expected_status": "answered", "result": result.model_dump(mode="json"),
        "result_digest": result.digest(),
    }]}
    return captures, results, patch


@pytest.mark.parametrize("mutation", ["run", "execution", "question", "digest", "duplicate",
                                      "missing", "source_text", "source_location"])
def test_wrong_artifact_joins_or_sources_are_rejected(mutation: str) -> None:
    captures, results, _ = artifacts()
    attempt = results["attempts"][0]
    if mutation == "run":
        results["run"]["id"] = str(UUID(int=99))
    elif mutation == "execution":
        attempt["execution_id"] = str(UUID(int=99))
    elif mutation == "question":
        attempt["query"] = "다른 질문"
    elif mutation == "digest":
        attempt["result_digest"] = "0" * 64
    elif mutation == "duplicate":
        captures["attempts"].append(copy.deepcopy(captures["attempts"][0]))
    elif mutation == "missing":
        results["attempts"] = []
    else:
        result = attempt["result"]
        if mutation == "source_text":
            result["evidence"][0]["excerpt"] += "변조"
        else:
            result["evidence"][0]["source"]["location"]["page"] = 9
        attempt["result_digest"] = PrivateGenerativeResult.model_validate(result).digest()
    with pytest.raises(ValueError):
        load_records(captures, results, kind="synthetic_fixture")


def test_refusal_uses_status_check_not_positive_rubric() -> None:
    captures, results, patch = artifacts()
    attempt = results["attempts"][0]
    result = attempt["result"]
    result.update(answer=None, citations=[])
    result["observation"].update(generation_status="insufficient_evidence", cited_evidence_ids=[],
                                 citation_valid=None)
    attempt.update(expected_status="insufficient_evidence",
                   result_digest=PrivateGenerativeResult.model_validate(result).digest())
    records = load_records(captures, results, kind="synthetic_fixture")
    report = build_report(records, patch, {})
    assert "거절 반환 형식 일치" in report.html
    assert "expected_answer_missing" not in report.html
    assert all(c.execution_status == "not_run" for c in report.comparisons[0].candidates)


def test_html_escapes_untrusted_content_and_does_not_predict_results() -> None:
    captures, results, patch = artifacts()
    attack = '<script>alert("test")</script><img src=x onerror=alert(1)>'
    result = results["attempts"][0]["result"]
    result["answer"] = result["citations"][0]["claim_text"] = attack
    results["attempts"][0]["result_digest"] = (
        PrivateGenerativeResult.model_validate(result).digest()
    )
    records = load_records(captures, results, kind="synthetic_fixture")
    report = build_report(records, patch, {})
    assert "<script>" not in report.html and "<img " not in report.html
    assert "&lt;script&gt;" in report.html
    assert "과거 결과" in report.html and "미실행" in report.html
    assert "원인 미확정" in report.html
    assert "http://" not in report.html and "https://" not in report.html


def test_output_refuses_existing_directory_and_preserves_inputs(tmp_path: Path) -> None:
    captures, results, patch = artifacts()
    report = build_report(load_records(captures, results, kind="synthetic_fixture"), patch, {})
    target = tmp_path / "report"
    write_report(report, target)
    before = {p.name: p.read_bytes() for p in target.iterdir()}
    with pytest.raises(FileExistsError):
        write_report(report, target)
    assert before == {p.name: p.read_bytes() for p in target.iterdir()}
    assert (target / "index.html").exists() and (target / "candidates.json").exists()


def test_changing_reviewer_requirements_cannot_change_candidate_inputs() -> None:
    captures, results, patch = artifacts()
    records = load_records(captures, results, kind="synthetic_fixture")
    record = records[0]
    support = Evidence(evidence_id=UUID(int=1), text=str(record.evidence[0]["text"]))
    rubric = Rubric(version=1, rules=(Rule(key="borrower_condition", terms=(("성인",),),
                                         support=(support,)),))
    without = build_report(records, patch, {})
    with_review = build_report(records, patch, {record.case_id: rubric})
    assert without.comparisons == with_review.comparisons
    assert without.html != with_review.html
    assert "필수 규칙 표현을 답변에서 찾지 못함" in with_review.html
