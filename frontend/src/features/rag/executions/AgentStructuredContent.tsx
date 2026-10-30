"use client";

import { useId, useState, type ReactNode } from "react";
import type { components } from "../../../shared/api/schema";
import styles from "./AgentSpanModal.module.css";

type AgentContent = components["schemas"]["AgentContent"];
const contentStates: Record<AgentContent["content_status"], [string, string]> = {
  complete: ["본문 기록됨", ""],
  not_retained: ["당시 본문 미보관", "이 실행 당시 본문을 보관하지 않아 다시 확인할 수 없습니다. 과거 내용을 복원하지 않습니다."],
  disabled: ["당시 본문 수집 안 함", "기록 당시 이 항목의 본문을 수집하지 않았습니다. 빈 입력이나 빈 결과라는 뜻은 아닙니다."],
  not_applicable: ["해당 없음", "이 단계에는 이 항목이 해당하지 않습니다."],
  omitted_size_limit: ["크기 제한으로 본문 생략", "표시용 기록 한도를 넘어 본문 전체를 생략했습니다. 실제 입력이나 결과가 잘렸다는 뜻은 아닙니다."],
  omitted_validation_failure: ["답변 검증 실패로 본문 숨김", "인용 또는 답변 검증을 통과하지 못한 결과이므로 본문을 표시하지 않습니다. 길이와 해시만 기록되었습니다."],
};

// Only observed field names get presentation labels. Unknown data stays in the original.
const fieldLabels: Record<string, string> = {
  question: "질문", resolved_query: "재작성 검색 질의", delegated_task: "위임된 작업", task: "작업 요청",
  history: "대화 이력", messages: "메시지", role: "메시지 역할", content: "내용",
  evidence: "검색 근거", evidence_groups: "근거 공통 정보", available_evidence_count: "전달 가능한 근거 수",
  evidence_sources: "근거 출처", evidence_blocks: "근거 블록", fragments: "근거 조각",
  source_ref: "근거 출처 참조", source_kind: "근거 종류", section_path: "문서 내 위치",
  evidence_id: "근거 ID", evidence_ids: "인용 근거 ID", text: "본문", title: "자료 제목", page: "쪽",
  group_ref: "근거 그룹 참조", group_id: "근거 그룹 ID", source_reading: "원문 읽기 자료",
  context_notice: "근거 문맥 안내", evidence_format_notice: "근거 형식 안내",
  claims: "답변 주장", status: "관측 응답 상태", tool: "도구", tools: "사용 가능한 도구",
  arguments: "호출 인자", function: "도구 정의", name: "이름", description: "설명", parameters: "인자 구조",
  tool_calls: "도구 호출", tool_choice: "도구 선택 설정", input: "입력", output: "출력",
};
const roles: Record<string, string> = {
  system: "시스템 (system)", developer: "개발자 (developer)", user: "사용자 (user)",
  assistant: "어시스턴트 (assistant)", tool: "도구 (tool)",
};
const MAX_DEPTH = 12;
const MAX_ITEMS = 40;
const MAX_RENDERED_VALUES = 250;
const MAX_PARSE_CHARACTERS = 32768;

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function parse(text: string): { parsed: true; value: unknown } | { parsed: false } {
  if (text.length > MAX_PARSE_CHARACTERS) return { parsed: false };
  try { return { parsed: true, value: JSON.parse(text) as unknown }; }
  catch { return { parsed: false }; }
}

function knownEntries(value: Record<string, unknown>) {
  return Object.entries(value).filter(([key]) => Object.hasOwn(fieldLabels, key));
}

function readable(value: unknown, depth: number, budget: { remaining: number }, field?: string): ReactNode {
  if (depth >= MAX_DEPTH) return <p className={styles.note}>중첩이 깊은 내용은 원문에서 확인하세요.</p>;
  if (budget.remaining-- <= 0) return <p className={styles.note}>정리 표시 한도에 도달했습니다. 나머지 내용은 원문에서 확인하세요.</p>;
  if (typeof value === "string") {
    if (field === "role") return <p className={styles.text}>{Object.hasOwn(roles, value) ? roles[value] : value}</p>;
    const nested = parse(value);
    if (nested.parsed && (isRecord(nested.value) || Array.isArray(nested.value))) {
      return readable(nested.value, depth + 1, budget);
    }
    return <p className={styles.text}>{value === "" ? "빈 문자열로 기록되었습니다." : value}</p>;
  }
  if (value === null || typeof value === "number" || typeof value === "boolean") {
    return <p className={styles.text}>{String(value)}</p>;
  }
  if (Array.isArray(value)) {
    if (!value.length) return <p className={styles.note}>항목 없음 (0개)</p>;
    return <>
      <ol className={styles.items}>{value.slice(0, MAX_ITEMS).map((item, index) => <li key={index}>
        {readable(item, depth + 1, budget)}
      </li>)}</ol>
      {value.length > MAX_ITEMS ? <p className={styles.note}>나머지 {value.length - MAX_ITEMS}개 항목은 원문에서 확인하세요.</p> : null}
    </>;
  }
  if (!isRecord(value)) return null;
  const entries = knownEntries(value);
  if (!entries.length) return <p className={styles.note}>알 수 없는 JSON 구조입니다. 원문에서 전체 내용을 확인하세요.</p>;
  const extraCount = Object.keys(value).length - entries.length;
  return <>
    <dl className={styles.fields}>{entries.map(([key, item]) => <div key={key}>
      <dt>{fieldLabels[key]}</dt><dd>{readable(item, depth + 1, budget, key)}</dd>
    </div>)}</dl>
    {extraCount ? <p className={styles.note}>그 밖의 저장 필드 {extraCount}개는 원문에 포함되어 있습니다.</p> : null}
  </>;
}

function ReadableBody({ text }: { text: string }) {
  if (text === "") return <p>빈 문자열로 기록되었습니다.</p>;
  const json = parse(text);
  return <div className={styles.readable}>{json.parsed
    ? readable(json.value, 0, { remaining: MAX_RENDERED_VALUES })
    : <p className={styles.text}>{text}</p>}</div>;
}

export function AgentStructuredContent({ title, content, showCompleteBody, note, validationContext = "answer" }: {
  title: string; content?: AgentContent; showCompleteBody: boolean; note?: string; validationContext?: "answer" | "observation";
}) {
  const headingId = useId();
  const [rawOpen, setRawOpen] = useState(false);
  // Decide access before passing text to parsing or any rendered node, including disclosures.
  const status = content?.content_status === "complete" && !showCompleteBody ? "not_retained" : content?.content_status;
  const visibleText = status === "complete" && content?.text != null ? content.text : null;
  const state = status === "omitted_validation_failure" && validationContext === "observation"
    ? ["관측 본문 검증 실패로 본문 숨김", "문맥화 응답의 관측 검증을 통과하지 못해 본문을 표시하지 않습니다. 이 상태만으로 답변 품질을 판단하지 않습니다."]
    : status ? contentStates[status] : undefined;
  return <section className={styles.content} aria-labelledby={headingId}>
    <h3 id={headingId}>{title}</h3>
    <p className={styles.contentStatus}>{state?.[0] ?? "본문 미기록"}</p>
    {note ? <p className={styles.note}>{note}</p> : null}
    {visibleText !== null ? <>
      <ReadableBody text={visibleText} />
      <details className={styles.disclosure} onToggle={event => setRawOpen(event.currentTarget.open)}>
        <summary>원문 펼치기</summary>
        {rawOpen ? <pre aria-label={`${title} 원문`}>{visibleText}</pre> : null}
      </details>
    </> : <p className={styles.note}>{state?.[1] || "이 항목에서 확인할 수 있는 본문이 없습니다."}</p>}
    <details className={styles.disclosure}>
      <summary>기록 정보</summary>
      <dl className={styles.facts}>
        <div><dt>문자 수</dt><dd>{content?.characters == null ? "미기록" : content.characters.toLocaleString("ko-KR")}</dd></div>
        <div><dt>SHA-256</dt><dd className={styles.identifier}>{content?.sha256 ?? "미기록"}</dd></div>
      </dl>
    </details>
  </section>;
}
