"""Standalone local diagnosis; reviewer data never enters model input preparation."""

import html
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from ai_workshop.labs.rag.evaluation.offline_input_artifacts import Record
from ai_workshop.labs.rag.evaluation.offline_input_diagnosis import (
    Comparison,
    InstructionChange,
    capture_body,
    content,
    prepare_comparison,
)
from ai_workshop.labs.rag.evaluation.offline_rubric import (
    Answer,
    Claim,
    Evidence,
    Example,
    Rubric,
    Rule,
    assess,
)

_STYLE = """
:root{color-scheme:dark;--bg:#0a0e13;--surface:#111921;--text:#e9edf3;
--muted:#b3bec7;--accent:#8ee6dc;--border:#33414e;--warning:#ffc38a}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);
font:16px/1.65 Inter,Pretendard,'Noto Sans KR','Malgun Gothic',sans-serif}
main{max-width:1480px;margin:auto;padding:32px 24px}h1{font-size:2rem;line-height:1.4}
h2{font-size:1.5rem}h3{font-size:1.15rem}a{color:var(--accent)}
p,li,td,th,summary,code{overflow-wrap:anywhere;word-break:keep-all}
.muted{color:var(--muted)}.warning{color:var(--warning)}
.panel,article{background:var(--surface);border:1px solid var(--border);
border-radius:12px;padding:20px;margin:20px 0;min-width:0}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:16px}
.grid>.panel{margin:0}.badge{display:inline-block;border:1px solid var(--border);
border-radius:6px;padding:2px 10px;margin:4px 8px 4px 0;color:var(--accent)}
blockquote{margin:12px 0;padding:12px;border-left:3px solid var(--accent);
background:var(--bg);white-space:pre-wrap;overflow-wrap:anywhere}
details{border-top:1px solid var(--border);padding:12px 0}
summary{cursor:pointer;min-height:44px;padding:8px 0;font-weight:600}
summary:focus-visible,a:focus-visible{outline:2px solid var(--accent);outline-offset:3px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.6 monospace;
background:var(--bg);padding:16px;border-radius:6px}code{font-size:.85rem}
table{border-collapse:collapse;width:100%;table-layout:fixed}
th,td{padding:10px;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}
nav ul{display:flex;flex-wrap:wrap;gap:12px 24px;padding-left:20px}
.source:target{outline:2px solid var(--accent);outline-offset:4px}
@media(max-width:700px){main{padding:20px 12px}.panel,article{padding:16px}h1{font-size:1.6rem}}
@media print{body{background:white;color:black}.muted,.warning,a{color:black}
.panel,article{background:white}pre,blockquote{background:#eee}details{break-inside:avoid}}
"""

_FINDINGS = {
    "required_rule_missing": "필수 규칙 표현을 답변에서 찾지 못함",
    "example_condition_missing": "인용한 예시의 조건 표현을 답변에서 찾지 못함",
    "example_support_incomplete": "예시의 조건을 뒷받침하는 인용 묶음이 부족함",
    "rule_support_incomplete": "일반 규칙을 뒷받침하는 인용 묶음이 부족함",
    "source_binding_mismatch": "검토 기준의 원문이 이번 전달 근거와 일치하지 않음",
}


@dataclass(frozen=True)
class Report:
    html: str
    comparisons: tuple[Comparison, ...]
    review_json: str


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _details(title: str, text: str) -> str:
    return f"<details><summary>{_esc(title)}</summary><pre>{_esc(text)}</pre></details>"


def _review(record: Record, rubric: Rubric | None) -> str:
    result = record.result
    if record.expected_status == "insufficient_evidence":
        if rubric is not None:
            raise ValueError("A positive rubric cannot judge a refusal case.")
        matches = (result.observation.generation_status == "insufficient_evidence"
                   and result.answer is None and not result.citations)
        label = "거절 반환 형식 일치" if matches else "기대 거절과 반환 결과 불일치"
        return (f"<p><strong>{label}</strong></p><p>답변 없음·인용 없음·상태를 검사했습니다. "
                "실제 근거가 부족한지는 원문을 보고 별도로 판단해야 합니다.</p>")
    if rubric is None:
        return "<p>검토 기준 미제공 · 원문과 답변의 의미 검토가 필요합니다.</p>"
    if any(c.claim_text is None for c in result.citations):
        return "<p>주장별 원문 기록 없음 · 현재 답변으로 인용 주장을 재구성하지 않습니다.</p>"
    evidence = tuple(Evidence(evidence_id=UUID(str(e["evidence_id"])), text=str(e["text"]))
                     for e in record.evidence)
    claims = tuple(Claim(text=c.claim_text or "", evidence_ids=c.evidence_ids)
                   for c in result.citations)
    status = result.observation.generation_status
    answer = Answer(
        status=("answered" if status == "answered" else
                "insufficient_evidence" if status == "insufficient_evidence" else "error"),
        answer=result.answer or "", claims=claims,
        citation_validation="passed" if result.observation.citation_valid else "failed",
    )
    outcome = assess(answer, rubric, evidence)
    items = "".join(
        f"<li>{_esc(_FINDINGS.get(f.code, f.code))}"
        f"{(' · 기준 '+_esc(f.criterion)) if f.criterion else ''}"
        f"{(' · 주장 '+str(f.claim_index + 1)) if f.claim_index is not None else ''}</li>"
        for f in outcome.findings
    )
    if not items:
        items = "<li>등록한 문자열 검사를 충족했습니다. 의미 정답 여부는 미검토입니다.</li>"
    supports = ""
    criteria: tuple[Rule | Example, ...] = (*rubric.rules, *rubric.examples)
    for criterion in criteria:
        quotes = "".join(f"<blockquote>{_esc(q.text)}</blockquote>" for q in criterion.support)
        supports += (f"<details><summary>판정 근거 · {_esc(criterion.key)}</summary>"
                     f"{quotes}</details>")
    return (f'<p class="warning"><strong>자동 점검: {_esc(outcome.status)}</strong></p>'
            f"<ul>{items}</ul><p>문자열·인용 묶음 검사입니다. 동의 표현이나 의미 정확성은 "
            "별도 검토하며, 날짜 예시 자체가 거짓이라고 판정하는 검사가 아닙니다.</p>"
            f"{supports}")


def _record_section(record: Record, comparison: Comparison, rubric: Rubric | None) -> str:
    key = str(record.capture.attempt_id)
    sources = {str(e["evidence_id"]): str(e["text"]) for e in record.evidence}
    cited = {str(eid) for c in record.result.citations for eid in c.evidence_ids}
    claims = ""
    for claim in record.result.citations:
        links = " · ".join(
            f'<a href="#e-{key}-{eid}">{_esc(eid)}</a>' if str(eid) in sources
            else f"알 수 없는 인용 {_esc(eid)}" for eid in claim.evidence_ids
        )
        claims += (f"<p>주장 {claim.claim_index + 1}</p>"
                   f"<blockquote>{_esc(claim.claim_text or '주장별 원문 없음')}</blockquote>"
                   f"<p>{links or '인용 없음'}</p>")
    evidence = "".join(
        f'<div class="source" id="e-{key}-{_esc(e["evidence_id"])}">'
        f'<p><code>{_esc(e["evidence_id"])}</code>'
        f' · {"답변에서 인용" if str(e["evidence_id"]) in cited else "전달됐으나 인용 안 됨"}</p>'
        f'<blockquote>{_esc(e["text"])}</blockquote>'
        f'<p class="muted">문자 위치 {_esc(e.get("char_range"))} · '
        f'원문 순서 {_esc(e.get("ordinal"))} · 좌표 {_esc(e.get("bbox"))}</p></div>'
        for e in record.evidence
    )
    candidates = ""
    names = {"A": "원본 그대로", "B": "JSON 줄배치만 변경", "C": "답변 지침 구간만 변경"}
    for candidate in comparison.candidates:
        candidates += (
            f'<div class="panel"><h4>{candidate.condition} · {names[candidate.condition]}</h4>'
            '<span class="badge">미실행 · 새 답변 없음</span>'
            f"<p>{candidate.body_bytes:,} bytes · 문자/바이트와 토큰 수는 다릅니다.</p>"
            f"<p>변경 필드: {_esc(candidate.changed_field)}</p>"
            "<p>원문·순서·출처·생성 옵션 보존 검사 통과</p>"
            f"<p><code>SHA-256 {_esc(candidate.sha256)}</code></p>"
            + _details("원본 대비 변경 내용", candidate.diff or "변경 없음 · 원본과 바이트 일치")
            + _details("준비된 최종 허용 필드 JSON", candidate.request_json) + "</div>"
        )
    actual = record.capture.kind == "actual_capture"
    origin = "실제 캡처와 저장 결과" if actual else "합성 fixture · 실제 전송 증거 아님"
    answer = (record.result.answer if record.result.answer is not None
              else "answer: null · 답변 본문 없음")
    input_label = "실제 최종" if actual else "합성 fixture"
    return (
        f'<article id="attempt-{key}"><h2>{_esc(record.question)}</h2>'
        f'<p class="muted">{origin} · 반복 {record.repetition} · '
        "회차 번호는 실행 순서를 뜻하지 않습니다.</p>"
        '<div class="grid"><div class="panel"><h3>1. 전달된 근거</h3>'
        f"<p>{len(record.evidence)}개 원문의 ID·본문·위치가 저장 결과와 일치합니다.</p>"
        '<p>선택 근거의 전달은 모델의 이해를 입증하지 않습니다.</p>'
        f"<details><summary>전체 근거와 인용 여부 보기</summary>{evidence}</details></div>"
        '<div class="panel"><h3>2. 과거 결과 · 실제 답변</h3>'
        f"<blockquote>{_esc(answer)}</blockquote>"
        f"<p>상태: {_esc(record.result.observation.generation_status)} · "
        f"인용 ID 검사: {_esc(record.result.observation.citation_valid)}</p>"
        f"<details><summary>주장별 인용 대조</summary>{claims or '주장/인용 없음'}</details></div>"
        '<div class="panel"><h3>3. 무엇이 빠졌나</h3>' + _review(record, rubric) + "</div></div>"
        + _details(f"{input_label} system 지침", content(capture_body(record.capture), 0))
        + _details(f"{input_label} user 입력", content(capture_body(record.capture), 1))
        + f"<h3>원인 비교를 위한 입력 후보</h3><div class=\"grid\">{candidates}</div>"
        + _details("출처와 무결성 기록", json.dumps({
            "run_id": str(record.capture.run_id), "attempt_id": key,
            "execution_id": str(record.capture.execution_id), "case_id": str(record.case_id),
            "capture_sha256": record.capture.sha256, "result_sha256": record.result_sha256,
            "transform_version": comparison.version, "model": record.capture.model,
            "model_version": record.capture.model_version,
            "provider": record.capture.provider, "dialect": record.capture.dialect,
            "prompt_ref": record.capture.prompt_ref,
            "profile_version": record.capture.profile_version,
            "future_model_calls": 0,
        }, ensure_ascii=False, indent=2)) + "</article>"
    )


def build_report(
    records: tuple[Record, ...], patch: InstructionChange, reviews: Mapping[UUID, Rubric],
) -> Report:
    if not records or set(reviews) - {record.case_id for record in records}:
        raise ValueError("Empty records or unrelated review criteria.")
    # No answers or reviewer criteria are accepted by prepare_comparison.
    comparisons = tuple(prepare_comparison(record.capture, patch) for record in records)
    sections = "".join(_record_section(record, comparison, reviews.get(record.case_id))
                       for record, comparison in zip(records, comparisons, strict=True))
    navigation = "".join(f'<li><a href="#attempt-{r.capture.attempt_id}">'
                         f'{_esc(r.question)} · {r.repetition}회</a></li>' for r in records)
    page = (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" '
        'content="default-src \'none\'; style-src \'unsafe-inline\'; base-uri \'none\'; '
        'form-action \'none\'">'
        f'<title>RAG 입력·답변 비교 진단</title><style>{_STYLE}</style></head><body><main>'
        '<h1>RAG 입력·답변 비교 진단</h1>'
        '<p>질문에 필요한 규칙과 조건이 실제 답변에 반영됐는지 확인하세요.</p>'
        '<div class="panel"><strong>과거 결과 대조 완료 · A/B/C 후보는 모두 미실행</strong>'
        '<p>이 도구는 모델·임베딩·DB·HTTP를 호출하지 않습니다. 과거 A 답변을 B/C의 결과로 '
        '사용하지 않습니다. 판정 기준과 정답은 후보 입력에 넣지 않습니다.</p>'
        '<p class="warning">원인 미확정: 후보 실행 전에는 개선 효과를 알 수 없습니다. '
        'B는 JSON 줄배치만 바꾸며 표 관계를 복원하지 않습니다. C는 지정한 답변 지침 구간만 '
        '바꿉니다. 그 구간의 의미상 적절성은 사람이 검토해야 합니다.</p>'
        '<p>후속 비교는 같은 실험에서 A도 실행하고 반복 수·순서·실행 환경을 통제해야 합니다. '
        '모두 실패해도 모델 자체의 한계를 확정할 수 없습니다. 생성 단계 비교는 전체 RAG '
        'P95 수용 평가를 대신하지 않습니다.</p>'
        '<p class="muted">캡처는 최종 어댑터의 허용 필드입니다. 공급자 내부 입력 절단·캐시·'
        '내부 해석은 미확인입니다. 해시 대조는 저장 파일 간 일치 검사이며 독립적인 네트워크 '
        '전송 증명이나 현재 원문 접근 권한 검사가 아닙니다.</p></div>'
        f'<nav aria-label="평가 사례"><ul>{navigation}</ul></nav>{sections}</main></body></html>'
    )
    review_json = json.dumps({str(key): value.model_dump(mode="json")
                              for key, value in reviews.items()}, ensure_ascii=False, indent=2)
    return Report(html=page, comparisons=comparisons, review_json=review_json)


def write_report(report: Report, output: Path) -> None:
    """Create a new directory only; never replace inputs or earlier reports."""
    destination = output.absolute()
    if any(p.is_symlink() or p.is_junction() for p in (destination, *destination.parents)):
        raise ValueError("Linked output directories are not supported.")
    # All validation/rendering finishes before the first write. Partial output is
    # preserved on an I/O failure; no destructive cleanup or retry is attempted.
    destination.mkdir(parents=True, exist_ok=False)
    payload = json.dumps({
        "classification": "public_synthetic", "execution_status": "not_run",
        "comparisons": [c.model_dump(mode="json") for c in report.comparisons],
    }, ensure_ascii=False, indent=2)
    for name, value in (("index.html", report.html), ("candidates.json", payload),
                        ("review-only.json", report.review_json)):
        with (destination / name).open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
