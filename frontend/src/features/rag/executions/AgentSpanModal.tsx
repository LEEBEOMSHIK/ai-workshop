"use client";

import { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";
import { buildSourceHref } from "../search/source-route-query";
import { duration } from "./ExecutionStages";
import { AgentStructuredContent } from "./AgentStructuredContent";
import { AgentHttpInstructions, AgentPurposeDetails, AgentStepMaterials, AgentStepOverview } from "./AgentStepOverview";
import { inspectStepContent } from "./agent-step-overview";
import { relatedMaterialStages } from "./agent-materials";
import { AgentPurposeHelpProvider, type AgentHelpController } from "./AgentPurposeHelp";
import { observedModels, type AgentFlow, type AgentSpan } from "./agent-flow";
import styles from "./AgentSpanModal.module.css";

const kinds: Record<AgentSpan["kind"], string> = { agent: "에이전트", delegation: "위임", tool: "도구", model: "모델 호출" };
const states: Record<AgentSpan["state"], string> = { running: "진행 중", completed: "처리 완료", failed: "실패", cancelled: "취소" };
const inputKinds: Record<AgentSpan["input_kind"], string> = {
  sdk_input: "SDK 실행 입력", http_request: "HTTP 요청 본문", tool_arguments: "도구 호출 인자",
};

function relationshipSummary(span: AgentSpan, parent: AgentSpan | undefined, flow: AgentFlow) {
  if (span.kind === "delegation") return `${span.from_agent ?? "주체 미기록"} → ${span.to_agent ?? "대상 미기록"}: 작업을 맡기기 위한 위임 요청입니다.`;
  const agent = flow.byAgentId.get(span.id);
  if (span.kind === "agent" && agent) {
    const incoming = agent.incoming;
    if (incoming?.delegations.length) return `${flow.byId.get(incoming.sourceId)?.name ?? "상위 에이전트 미기록"}의 ${incoming.delegations[0].name} 위임 요청을 처리하는 에이전트입니다.`;
    const outgoing = agent.outgoing.find(link => link.delegations.length);
    if (outgoing) return `${flow.byId.get(outgoing.targetId)?.name ?? "대상 미기록"}에 작업을 맡기는 요청이 기록된 에이전트입니다.`;
    return span.parent_id ? parent ? `${parent.name}에 속한 에이전트 실행입니다.` : "상위 관계 미기록" : "이 실행이 시작된 에이전트입니다.";
  }
  return parent ? `${parent.name}에 속한 ${kinds[span.kind]} 기록입니다.` : span.parent_id ? "상위 단계 미기록" : `최상위 ${kinds[span.kind]} 기록입니다.`;
}

function ObservedRelationship({ span, parent, flow }: { span: AgentSpan; parent?: AgentSpan; flow: AgentFlow }) {
  if (span.kind === "delegation") return <div className={styles.relationship}>
    <p><strong>{span.from_agent ?? "위임한 에이전트 미기록"}</strong> → <strong>{span.to_agent ?? "위임 대상 미기록"}</strong></p>
    <p>{span.name} 도구의 위임 요청 기록입니다.</p>
    <p>{span.delegation_mode === "as_tool" ? "결과를 돌려받는 도구 위임 (as_tool)"
      : span.delegation_mode === "handoff" ? "제어권 인계 (handoff)" : "위임 방식 미기록"}</p>
  </div>;
  const agent = flow.byAgentId.get(span.id);
  if (span.kind !== "agent" || !agent) return <p className={styles.note}>
    {parent ? `기록 #${parent.sequence + 1} ${parent.name}에 속한 ${kinds[span.kind]} 기록입니다.`
      : span.parent_id ? "상위 단계 미기록" : "최상위 단계 기록입니다."}
  </p>;
  const incoming = agent.incoming;
  return <div className={styles.relationship}>
    {incoming?.delegations.length ? incoming.delegations.map(delegation => <p key={delegation.id}>
      {flow.byId.get(incoming.sourceId)?.name ?? "상위 에이전트 미기록"}의 {delegation.name} 도구를 통한 위임 요청 대상입니다.
    </p>) : <p>{incoming ? "기록된 상위 에이전트에 속한 실행입니다." : span.parent_id ? "상위 관계 미기록" : "이 실행의 시작 에이전트입니다."}</p>}
    {agent.outgoing.flatMap(link => link.delegations.map(delegation => <p key={delegation.id}>
      {delegation.name} 도구로 {flow.byId.get(link.targetId)?.name ?? "대상 미기록"}에 작업을 위임 요청한 기록입니다.
    </p>))}
    <p>관측된 모델: {observedModels(agent)}</p>
  </div>;
}

function focusableElements(panel: HTMLElement) {
  return Array.from(panel.querySelectorAll<HTMLElement>(
    'button:not([disabled]), a[href], summary, input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )).filter(element => {
    if (element.closest("[hidden], [inert]")) return false;
    for (let ancestor: HTMLElement | null = element; ancestor && ancestor !== panel; ancestor = ancestor.parentElement) {
      if (getComputedStyle(ancestor).display === "none" || getComputedStyle(ancestor).visibility === "hidden") return false;
      if (ancestor instanceof HTMLDetailsElement && !ancestor.open
        && !ancestor.querySelector(":scope > summary")?.contains(element)) return false;
    }
    return true;
  });
}

function restoreFocus(opener: Element | null, spanId: string, openedSpanId: string) {
  const replacement = Array.from(document.querySelectorAll<HTMLElement | SVGElement>("[data-agent-span-id]"))
    .find(node => node.getAttribute("data-agent-span-id") === spanId);
  const target = spanId === openedSpanId && opener?.isConnected && "focus" in opener ? opener
    : replacement ?? document.querySelector<HTMLElement>('[aria-label="에이전트 위임 그림"]');
  if (target && "focus" in target && typeof target.focus === "function") target.focus({ preventScroll: true });
}

export function AgentSpanModal({ span, parent, flow, showCompleteBody, onClose, id, initialSection, onSelectMaterials }: {
  span: AgentSpan; parent?: AgentSpan; flow: AgentFlow; showCompleteBody: boolean; onClose: () => void; id?: string;
  initialSection?: "materials"; onSelectMaterials?: (spanId: string) => void;
}) {
  const titleId = useId();
  const panel = useRef<HTMLElement>(null);
  const backdrop = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  const closeRef = useRef(onClose);
  const spanIdRef = useRef(span.id);
  const helpController = useRef<AgentHelpController>(null);
  const inputOverview = inspectStepContent(span.input, showCompleteBody, "input");
  const outputOverview = inspectStepContent(span.output, showCompleteBody, "output");
  const relatedMaterials = relatedMaterialStages(span.id, flow, showCompleteBody);
  useEffect(() => { closeRef.current = onClose; spanIdRef.current = span.id; }, [onClose, span.id]);
  useEffect(() => {
    const opener = document.activeElement;
    const openedSpanId = spanIdRef.current;
    const overflow = document.body.style.overflow;
    const inertSiblings = Array.from(document.body.children).filter((node): node is HTMLElement =>
      node instanceof HTMLElement && node !== backdrop.current,
    ).map(node => ({ node, inert: node.hasAttribute("inert") }));
    for (const { node } of inertSiblings) node.setAttribute("inert", "");
    document.body.style.overflow = "hidden";
    closeButton.current?.focus();
    function keyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault(); event.stopPropagation();
        if (!helpController.current?.dismiss()) closeRef.current();
        return;
      }
      if (event.key !== "Tab" || !panel.current) return;
      const controls = focusableElements(panel.current);
      const first = controls[0]; const last = controls.at(-1);
      const active = document.activeElement;
      if (!first || !last) { event.preventDefault(); panel.current.focus(); return; }
      if (event.shiftKey && (active === first || !panel.current.contains(active))) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && (active === last || !panel.current.contains(active))) { event.preventDefault(); first.focus(); }
    }
    function keepFocus(event: FocusEvent) {
      if (event.target instanceof Node && !panel.current?.contains(event.target)) closeButton.current?.focus();
    }
    document.addEventListener("keydown", keyDown, true);
    document.addEventListener("focusin", keepFocus);
    return () => {
      document.removeEventListener("keydown", keyDown, true);
      document.removeEventListener("focusin", keepFocus);
      document.body.style.overflow = overflow;
      for (const { node, inert } of inertSiblings) if (!inert) node.removeAttribute("inert");
      restoreFocus(opener, spanIdRef.current, openedSpanId);
    };
  }, []);
  useEffect(() => {
    if (initialSection !== "materials") return;
    const summary = panel.current?.querySelector<HTMLElement>("[data-agent-materials-summary]");
    summary?.focus(); summary?.scrollIntoView?.({ block: "start" });
  }, [span.id, initialSection]);

  if (typeof document === "undefined") return null;
  return createPortal(<div ref={backdrop} className={styles.backdrop} onClick={event => {
    event.stopPropagation(); if (event.target === event.currentTarget) onClose();
  }}>
    <section id={id} ref={panel} className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby={titleId} tabIndex={-1}>
      <header className={styles.header}>
        <div><p className={styles.eyebrow}>기록 #{span.sequence + 1} · 단계 상세</p><h2 id={titleId}>{kinds[span.kind]} · {span.name}</h2></div>
        <button ref={closeButton} type="button" onClick={onClose}>닫기</button>
      </header>
      <div className={styles.scrollBody}>
        <div className={styles.statusRow}><span data-state={span.state} className={styles.state}>{states[span.state]}</span><span>{duration(span.duration_ms)}</span></div>
        {span.error_code ? <p role="alert" className={styles.warning}>실패 코드: <code>{span.error_code}</code></p> : null}
        {span.state === "cancelled" ? <p className={styles.warning}>단계 취소 기록이며 실제 모델 실행 종료 여부는 별도 확인이 필요합니다.</p> : null}
        <p className={styles.roleSummary} aria-label="관측된 역할">{relationshipSummary(span, parent, flow)}</p>
        <AgentPurposeHelpProvider key={span.id} controller={helpController}>
          <AgentStepOverview input={inputOverview} output={outputOverview} />
          <AgentPurposeDetails title="적용 지침">
            <AgentHttpInstructions input={inputOverview} />
            {span.instructions?.content_status === "not_applicable" && inputOverview.context.instructions.length ? null
              : <AgentStructuredContent title="적용 지침 원문" content={span.instructions} showCompleteBody={showCompleteBody} />}
          </AgentPurposeDetails>
          <AgentStepMaterials input={inputOverview} related={relatedMaterials} onSelect={onSelectMaterials}
            initiallyOpen={initialSection === "materials"} />
          <AgentPurposeDetails title="원문·기술 기록">
        <ObservedRelationship span={span} parent={parent} flow={flow} />
        <p className={styles.note}>{inputKinds[span.input_kind ?? "sdk_input"]}</p>
        {span.kind === "model" ? <dl className={styles.facts}>
          <div><dt>모델</dt><dd>{span.model_name ?? "미기록"}</dd></div>
          <div><dt>공급자 보고 입력</dt><dd>{span.input_tokens == null ? "미보고" : `${span.input_tokens.toLocaleString("ko-KR")} 토큰`}</dd></div>
          <div><dt>공급자 보고 출력</dt><dd>{span.output_tokens == null ? "미보고" : `${span.output_tokens.toLocaleString("ko-KR")} 토큰`}</dd></div>
        </dl> : null}
        <div className={styles.contents}>
          <div className={styles.requestStack}>
            <AgentStructuredContent title="전달 지침" content={span.instructions} showCompleteBody={showCompleteBody} />
            <AgentStructuredContent title="전달 입력" content={span.input} showCompleteBody={showCompleteBody}
              note="이 단계에 기록된 입력입니다. SDK 실행 입력과 실제 HTTP 요청 본문은 서로 다를 수 있습니다." />
          </div>
          <AgentStructuredContent title="반환 결과" content={span.output} showCompleteBody={showCompleteBody}
            note="단계에서 관측한 반환값이며, 검증된 최종 답변과 구분합니다." />
        </div>
        <details className={styles.disclosure}>
          <summary>연결된 원문 ({span.evidence_refs?.length ?? 0})</summary>
          {span.evidence_refs?.length ? <ul className={styles.sources}>{span.evidence_refs.map((ref, index) => <li key={`${ref.asset_version_id}:${ref.projection_id}:${index}`}>
            {ref.projection_id ? <a href={buildSourceHref(ref.asset_version_id, ref.projection_id)}>원문 {index + 1} 열기</a> : <span>원문 연결 정보 미기록</span>}
            <span className={styles.identifier}>문서 {ref.document_id} · 버전 {ref.asset_version_id}</span>
          </li>)}</ul> : <p className={styles.note}>연결된 원문 참조가 없습니다.</p>}
        </details>
        <details className={styles.disclosure}>
          <summary>단계 기록 정보</summary>
          <dl className={styles.facts}>
            <div><dt>단계 ID</dt><dd className={styles.identifier}>{span.id}</dd></div>
            <div><dt>상위 단계</dt><dd>{parent ? `#${parent.sequence + 1} ${parent.name}` : span.parent_id ? "상위 단계 미기록" : "최상위 실행"}</dd></div>
            <div><dt>상위 단계 ID</dt><dd className={styles.identifier}>{span.parent_id ?? "없음"}</dd></div>
            <div><dt>시작</dt><dd><time dateTime={span.started_at}>{new Date(span.started_at).toLocaleString("ko-KR")}</time></dd></div>
            <div><dt>종료</dt><dd>{span.ended_at ? <time dateTime={span.ended_at}>{new Date(span.ended_at).toLocaleString("ko-KR")}</time> : "종료 시각 미기록"}</dd></div>
          </dl>
        </details>
          </AgentPurposeDetails>
        </AgentPurposeHelpProvider>
      </div>
    </section>
  </div>, document.body);
}
