import { useRef, useState } from "react";
import type { AuthoringCase, AuthoringEvidence, AuthoringPreview } from "./api";

export function EvaluationCaseEditor({ value, index, evidence, documents, onChange, onRemove }: {
  value: AuthoringCase; index: number; evidence: AuthoringEvidence[]; documents: AuthoringPreview["documents"];
  onChange: (value: AuthoringCase) => void; onRemove: () => void;
}) {
  const [page, setPage] = useState(0);
  const [error, setError] = useState("");
  const [highlightKind, setHighlightKind] = useState<"keyword" | "semantic">("semantic");
  const texts = useRef(new Map<string, HTMLTextAreaElement>());
  function highlight(unit: AuthoringEvidence) {
    const textarea = texts.current.get(unit.id);
    if (!textarea || !value.expected_evidence_ids.includes(unit.id)) { setError("먼저 해당 정답 근거를 선택해 주세요."); return; }
    const start = unit.start_char + Array.from(unit.text.slice(0, textarea.selectionStart)).length;
    const end = unit.start_char + Array.from(unit.text.slice(0, textarea.selectionEnd)).length;
    // Reject a browser selection splitting a surrogate pair rather than fabricate an offset.
    const boundary = (offset: number) => offset === 0 || offset === unit.text.length || !(unit.text.charCodeAt(offset - 1) >= 0xd800 && unit.text.charCodeAt(offset - 1) <= 0xdbff && unit.text.charCodeAt(offset) >= 0xdc00 && unit.text.charCodeAt(offset) <= 0xdfff);
    if (!boundary(textarea.selectionStart) || !boundary(textarea.selectionEnd) || start >= end || end > unit.end_char) { setError("지원되는 원문 문자 구간을 선택해 주세요. 좌표만 있는 자료는 이 작성 화면에서 지원하지 않습니다."); return; }
    setError("");
    onChange({ ...value, expected_highlight: { kind: highlightKind, surface: "answer", document_id: unit.document_id, asset_version_id: unit.asset_version_id, evidence_unit_id: unit.id, page: unit.page ?? null, spans: [[start, end]], bboxes: [] } });
  }
  return <fieldset><legend>사례 {index + 1}</legend>
    <label>질문 {index + 1}<textarea value={value.query} maxLength={4000} onChange={(event) => onChange({ ...value, query: event.target.value })} /></label>
    <label>기대 결과 {index + 1}<select value={value.expected_answer_status} onChange={(event) => {
      setError(""); onChange({ ...value, expected_answer_status: event.target.value === "supported" ? "supported" : "insufficient_evidence", expected_evidence_ids: [], expected_highlight: null });
    }}><option value="supported">근거 있음</option><option value="insufficient_evidence">근거 부족</option></select></label>
    {value.expected_answer_status === "supported" ? <>
      <p>검색·모델 출력이 아닌 원문에서 정답 근거를 고르세요. 원문 입력란에서 키보드나 마우스로 구간을 선택한 뒤 지정 버튼을 누르세요. 위치는 Unicode 문자 기준입니다.</p>
      <label>하이라이트 종류 {index + 1}<select value={highlightKind} onChange={(event) => { setHighlightKind(event.target.value === "keyword" ? "keyword" : "semantic"); onChange({ ...value, expected_highlight: null }); }}><option value="semantic">의미 근거</option><option value="keyword">정확한 문자열</option></select></label>
      {evidence.slice(page * 10, page * 10 + 10).map((unit, offset) => {
        const ordinal = page * 10 + offset + 1;
        const document = documents.find((item) => item.asset_version_id === unit.asset_version_id);
        return <article key={unit.id}>
          <p>{document?.title ?? "선택된 원문"} {document ? `v${document.number}` : ""} · 근거 {ordinal}</p>
          <label><input type="checkbox" checked={value.expected_evidence_ids.includes(unit.id)} onChange={(event) => onChange({ ...value,
            expected_evidence_ids: event.target.checked ? [...value.expected_evidence_ids, unit.id] : value.expected_evidence_ids.filter((id) => id !== unit.id),
            expected_highlight: !event.target.checked && value.expected_highlight?.evidence_unit_id === unit.id ? null : value.expected_highlight,
          })} />정답 근거 {ordinal}</label>
          <label>근거 원문 {ordinal}<textarea readOnly value={unit.text} ref={(element) => { if (element) texts.current.set(unit.id, element); else texts.current.delete(unit.id); }} /></label>
          <button type="button" onClick={() => highlight(unit)}>선택 구간을 기대 하이라이트로 지정</button>
          <details><summary>근거 기술 식별자</summary><p>{unit.id} · projection {unit.projection_id} · build {unit.index_build_id}</p></details>
        </article>;
      })}
      <button type="button" disabled={page === 0} onClick={() => setPage((current) => current - 1)}>이전 근거</button>
      <button type="button" disabled={(page + 1) * 10 >= evidence.length} onClick={() => setPage((current) => current + 1)}>다음 근거</button>
      {value.expected_highlight ? <p>기대 하이라이트 지정됨: {value.expected_highlight.spans.map((span) => span.join("–")).join(", ")}</p> : <p>정답 근거와 기대 하이라이트를 직접 지정해야 합니다.</p>}
    </> : <p>선택된 전체 자료에 정답 근거가 없다는 수동 판정입니다. 기대 근거와 하이라이트는 비웁니다.</p>}
    {error ? <p role="alert">{error}</p> : null}<button type="button" onClick={onRemove}>사례 {index + 1} 삭제</button>
  </fieldset>;
}
