"use client";

import { useId, useState, type ReactNode } from "react";
import type { StepOverview } from "./agent-step-overview";
import { AgentPurposeHelp } from "./AgentPurposeHelp";
import { hasReadableEvidence, type RelatedMaterialStage } from "./agent-materials";
import styles from "./AgentSpanModal.module.css";

const contentStates: Record<StepOverview["state"], string> = {
  complete: "본문 기록됨", missing: "본문 미기록", not_retained: "당시 본문 미보관", disabled: "당시 본문 수집 안 함",
  not_applicable: "해당 없음", omitted_size_limit: "크기 제한으로 본문 생략", omitted_validation_failure: "답변 검증 실패로 본문 숨김",
};
const PREVIEW_ITEMS = 3;
const PREVIEW_CHARACTERS = 600;

const purposeHelp: Record<string, string> = {
  "적용 지침": "이 단계가 따라야 하는 지침 원문입니다. 답변 방식이나 제약이 무엇이었는지 확인할 때 펼치세요.",
  "함께 전달된 자료": "현재 단계 입력에 기록된 대화 이력과 검색 근거입니다. 근거 본문이 다른 단계에 있으면 표시된 단계로 이동해 확인하세요.",
  "원문·기술 기록": "정확한 지침·입력·반환 원문과 모델·토큰·ID·시각입니다. 핵심 표시에서 생략된 내용이나 오류 원인을 확인할 때 펼치세요.",
};

export function AgentPurposeDetails({ title, children, initiallyOpen = false, materials = false }: {
  title: string; children: ReactNode; initiallyOpen?: boolean; materials?: boolean;
}) {
  const [open, setOpen] = useState(initiallyOpen);
  return <div className={styles.purposeGroup}>
    <details className={styles.purposeDetails} open={open} onToggle={event => setOpen(event.currentTarget.open)}>
      <summary data-agent-materials-summary={materials ? "true" : undefined}>{title}</summary>
      {open ? <div className={styles.purposeBody}>{children}</div> : null}
    </details>
    {Object.hasOwn(purposeHelp, title) ? <AgentPurposeHelp title={title} text={purposeHelp[title]} /> : null}
  </div>;
}

function PrimaryContent({ title, value }: { title: string; value: StepOverview }) {
  const headingId = useId();
  return <section aria-labelledby={headingId} className={styles.primaryCard}>
    <h3 id={headingId}>{title}</h3>
    {value.state !== "complete" ? <p className={styles.primaryEmpty}>{contentStates[value.state]}</p> : <>
      {value.kind === "tool_request" ? <p className={styles.contentKind}>도구 요청</p>
        : value.kind === "refusal" ? <p className={styles.contentKind}>근거 부족 응답</p> : null}
      <div className={styles.primaryText}>{value.items.slice(0, PREVIEW_ITEMS).map((item, index) => <div key={index}>
        {index === 0 && item.label === "질문" || item.label === "답변 내용" ? null : <p className={styles.primaryLabel}>{item.label}</p>}
        <p>{item.text.length > PREVIEW_CHARACTERS ? `${item.text.slice(0, PREVIEW_CHARACTERS)}…` : item.text}</p>
        {item.text.length > PREVIEW_CHARACTERS ? <p className={styles.note}>앞부분 600자입니다. 전체 내용은 원문·기술 기록에서 확인하세요.</p> : null}
      </div>)}</div>
      {value.note ? <p className={styles.primaryEmpty}>{value.note}</p> : null}
      {value.limited || value.items.length > PREVIEW_ITEMS ? <p className={styles.note}>정리 표시 범위를 제한했습니다. 전체 내용은 원문·기술 기록에서 확인하세요.</p> : null}
    </>}
  </section>;
}

export function AgentStepOverview({ input, output }: { input: StepOverview; output: StepOverview }) {
  return <>
    <div className={styles.primaryOverview}>
      <PrimaryContent title="받은 요청" value={input} />
      <PrimaryContent title="반환한 결과" value={output} />
    </div>
    <p className={styles.note}>반환한 결과는 단계에서 관측한 반환값이며, 최종 답변의 품질 통과를 뜻하지 않습니다.</p>
  </>;
}

function entryText(value: unknown, field: string) {
  if (typeof value === "string") return value;
  if (value !== null && typeof value === "object" && !Array.isArray(value)) {
    const item = (value as Record<string, unknown>)[field];
    if (typeof item === "string") return item;
    if (item === null || typeof item === "number" || typeof item === "boolean") return String(item);
  }
  return "이 항목의 본문은 원문·기술 기록에서 확인하세요.";
}

function messageRole(value: unknown) {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return "역할 미기록";
  const role = (value as Record<string, unknown>).role;
  if (typeof role !== "string") return "역할 미기록";
  const names: Record<string, string> = { user: "사용자 (user)", assistant: "어시스턴트 (assistant)", system: "시스템 (system)", developer: "개발자 (developer)", tool: "도구 (tool)" };
  return Object.hasOwn(names, role) ? names[role] : `기록된 역할: ${role}`;
}

const materialKinds = { agent: "에이전트", delegation: "위임", model: "모델 호출", tool: "도구" };

export function AgentStepMaterials({ input, related, onSelect, initiallyOpen }: {
  input: StepOverview; related?: RelatedMaterialStage[]; onSelect?: (id: string) => void; initiallyOpen?: boolean;
}) {
  const context = input.context;
  const any = context.history !== undefined || context.evidence !== undefined || context.availableEvidence !== undefined || context.rewrittenQuery !== undefined;
  return <AgentPurposeDetails title="함께 전달된 자료" initiallyOpen={initiallyOpen} materials>
    {input.state !== "complete" ? <p>{contentStates[input.state]}</p> : <>
      {context.rewrittenQuery !== undefined ? <section className={styles.materialSection}><h4>재작성 검색 질의</h4><p className={styles.text}>{context.rewrittenQuery || '""'}</p></section> : null}
      {context.availableEvidence !== undefined ? <p>{/^\d+$/.test(context.availableEvidence)
        ? `사용 가능한 근거 ${context.availableEvidence}개` : `사용 가능 근거 수의 기록값: ${context.availableEvidence}`}</p> : null}
      {context.evidenceCount !== undefined ? <p>입력에 기록된 근거 {context.evidenceCount}개</p> : null}
      {context.availableEvidence !== undefined && context.evidenceCount === undefined ? <p className={styles.note}>후보 개수이며, 이 단계에 전달된 근거 본문 개수가 아닙니다.</p> : null}
      {context.history !== undefined ? <section className={styles.materialSection}><h4>대화 이력</h4>
        {!context.history.length ? <p>대화 이력 0개</p> : <ol className={styles.materialList}>{context.history.map((item, index) => <li key={index}>
          <p className={styles.primaryLabel}>{messageRole(item)}</p><p className={styles.text}>{entryText(item, "content")}</p>
        </li>)}</ol>}
      </section> : null}
      {context.evidence !== undefined ? <section className={styles.materialSection}><h4>검색 근거 본문</h4>
        {!context.evidence.length ? <p>입력 근거 배열이 비어 있습니다.</p> : <ol className={`${styles.materialList} ${styles.evidenceList}`}>{context.evidence.map((item, index) => <li key={index}>
          <p className={styles.primaryLabel}>근거 조각 {index + 1}</p><p className={styles.text}>{entryText(item, "text")}</p>
        </li>)}</ol>}
      </section> : null}
      {!any ? <p className={styles.note}>구분할 수 있는 대화 이력·검색 근거 필드가 없습니다. 원문·기술 기록에서 전체 입력을 확인하세요.</p> : null}
      {input.limited ? <p className={styles.note}>일부 자료만 표시했습니다. 전체 입력은 원문·기술 기록에서 확인하세요.</p> : null}
    </>}
    {!hasReadableEvidence(input) && related !== undefined ? <section className={styles.relatedMaterials}>
      <h4>다른 단계의 근거 본문</h4>
      {related.length && onSelect ? <>
        <p className={styles.note}>아래 단계의 실제 입력을 엽니다.</p>
        <ul>{related.map(({ span, evidenceCount }) => <li key={span.id}>
          <button type="button" onClick={() => onSelect(span.id)}>#{span.sequence + 1} · {materialKinds[span.kind]} · {span.name} · 입력 근거 {evidenceCount}개 보기</button>
        </li>)}</ul>
      </> : <p className={styles.note}>연결된 상위·하위 단계에서 확인 가능한 근거 본문이 없습니다.</p>}
    </section> : null}
  </AgentPurposeDetails>;
}

export function AgentHttpInstructions({ input }: { input: StepOverview }) {
  if (!input.context.instructions.length) return null;
  return <section className={styles.materialSection}><h4>실제 HTTP 메시지에 포함된 지침</h4>
    {input.context.instructions.map((message, index) => <div key={index}>
      <p className={styles.primaryLabel}>{message.role === "system" ? "시스템 (system)" : "개발자 (developer)"}</p>
      <p className={styles.text}>{message.text}</p>
    </div>)}
  </section>;
}
