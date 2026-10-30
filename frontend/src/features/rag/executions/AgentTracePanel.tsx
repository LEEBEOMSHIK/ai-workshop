"use client";

import { useId, useState, type ReactNode } from "react";
import type { components } from "../../../shared/api/schema";
import { AgentSpanModal } from "./AgentSpanModal";
import { duration } from "./ExecutionStages";
import { AgentFlowDiagram } from "./AgentFlowDiagram";
import { buildAgentFlow } from "./agent-flow";
import type { ExecutionOutcome } from "./ExecutionOutcomeSummary";
import styles from "./AgentTracePanel.module.css";

type AgentTrace = components["schemas"]["AgentTrace"];
type AgentSpan = components["schemas"]["AgentSpan"];
type View = "history" | "current";

const kinds: Record<AgentSpan["kind"], string> = {
  agent: "에이전트", delegation: "위임", tool: "도구", model: "모델 호출",
};
const states: Record<AgentSpan["state"], string> = {
  running: "진행 중", completed: "처리 완료", failed: "실패", cancelled: "취소",
};
const observedOutputNote = "단계에서 관측한 반환값이며, 검증된 최종 답변과 구분합니다.";

function KindIcon({ kind }: { kind: AgentSpan["kind"] }) {
  const paths: Record<AgentSpan["kind"], ReactNode> = {
    agent: <><circle cx="12" cy="7" r="3" /><path d="M5 20v-3a7 7 0 0 1 14 0v3" /></>,
    delegation: <><path d="M4 5h7v14m0-7h9m-4-4 4 4-4 4M4 19h7" /><circle cx="4" cy="5" r="1" /></>,
    tool: <><path d="m5 19 9-9M14 4a5 5 0 0 0 6 6l-3-3 1-3a5 5 0 0 0-4 0ZM4 16l4 4" /></>,
    model: <><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 2v4m6-4v4M9 18v4m6-4v4M2 9h4m-4 6h4m12-6h4m-4 6h4M10 10h4v4h-4z" /></>,
  };
  return <svg className={styles.kindIcon} viewBox="0 0 24 24" fill="none" stroke="currentColor"
    strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">{paths[kind]}</svg>;
}

export function AgentTracePanel({ trace, view = "history", outcome }: { trace?: AgentTrace | null; view?: View; outcome?: ExecutionOutcome }) {
  const headingId = useId();
  const detailId = useId();
  const [selection, setSelection] = useState<{ runId: string; spanId: string; section?: "materials" } | null>(null);
  const [recordsView, setRecordsView] = useState<{ runId: string; open: boolean } | null>(null);
  const spans = trace?.spans ?? [];
  const flow = buildAgentFlow(spans);
  const { byId, children, roots, unlinked } = flow;
  const selected = selection?.runId === trace?.run_id ? spans.find(span => span.id === selection?.spanId) : undefined;
  const longest = Math.max(0, ...spans.map(span => span.duration_ms ?? 0));
  const cancelled = spans.filter(span => span.state === "cancelled").length;
  const failed = spans.filter(span => span.state === "failed").length;

  function nodes(items: AgentSpan[], parent?: AgentSpan, depth = 0): ReactNode {
    return <ol className={parent ? `${styles.children}${depth > 3 ? ` ${styles.compressed}` : ""}` : styles.nodes}
      aria-label={parent ? `${parent.name}의 하위 단계` : "에이전트 실행과 위임 단계"}>
      {items.map(span => {
        const active = span.id === selected?.id;
        const descendants = children.get(span.id);
        return <li key={span.id} className={styles.node}>
          <button type="button" aria-pressed={active} aria-haspopup="dialog" data-agent-span-id={span.id}
            aria-label={`${span.sequence + 1}. ${kinds[span.kind]} · ${span.name} · ${states[span.state]} · ${duration(span.duration_ms)}`}
            onClick={() => trace && setSelection({ runId: trace.run_id, spanId: span.id })}>
            <span className={styles.nodeTitle}><KindIcon kind={span.kind} /><span className={styles.nodeText}>
              <span className={styles.nodeHeading}>{kinds[span.kind]}{active ? <span className={styles.selection}>선택됨</span> : null}</span>
              <strong>{span.name}</strong>
            </span></span>
            {depth > 3 && parent ? <span className={styles.nodeParent}>상위 · {parent.name}</span> : null}
            {unlinked.has(span.id) ? <span className={styles.warning}>부모 연결 미확인</span> : null}
            <span className={styles.statusRow}><span data-state={span.state} className={styles.state}>{states[span.state]}</span><span className={styles.elapsed}>{duration(span.duration_ms)}</span></span>
          </button>
          {span.duration_ms == null ? null : <div className={styles.timeTrack} role="meter" aria-label={`${span.name} 관측 소요 시간`}
            aria-valuemin={0} aria-valuemax={longest || 1} aria-valuenow={span.duration_ms} aria-valuetext={duration(span.duration_ms)}>
            <span style={{ width: `${longest ? span.duration_ms / longest * 100 : 0}%` }} />
          </div>}
          {descendants?.length ? nodes(descendants, span, depth + 1) : null}
        </li>;
      })}
    </ol>;
  }

  return <section className={styles.panel} aria-labelledby={headingId}>
    <header className={styles.header}>
      <p className={styles.eyebrow}>OpenAI Agents SDK · 기록된 단계</p>
      <h2 id={headingId}>에이전트 위임 흐름</h2>
    </header>
    {!trace ? <p className={styles.empty}>에이전트 위임 기록이 없는 실행입니다. 이전 기록에서 실행 흐름을 추정하지 않습니다.</p> : <>
      <dl className={styles.overview} aria-label="기록된 단계 요약">
        {(["agent", "delegation", "model", "tool"] as const).map(kind => <div key={kind}>
          <dt><KindIcon kind={kind} />{kinds[kind]}</dt>
          <dd>{spans.filter(span => span.kind === kind).length} <span>단계</span></dd>
        </div>)}
      </dl>
      <p className={styles.notice}>{view === "history"
        ? trace.content_retention === "retained"
          ? "단계 본문 보관이 적용된 실행 기록입니다. 실제 수집·보관 여부는 각 항목의 상태를 확인하세요."
          : "이 실행 이력에는 본문이 보관되지 않았습니다. 당시 미수집·미보관 본문은 복원하지 않습니다."
        : "현재 응답의 단계 기록입니다. 본문 수집·보관 여부는 각 항목의 상태를 확인하세요."}</p>
      <p className={styles.notice}>{observedOutputNote}</p>
      {!trace.observation_complete ? <p role="status" className={styles.warning}>일부 관측 기록이 누락되었습니다. 표시된 단계가 전체 실행을 나타내지 않을 수 있습니다.</p> : null}
      {trace.truncated ? <p role="status" className={styles.warning}>기록 한도를 넘어 일부 단계 또는 본문이 생략되었습니다.</p> : null}
      {cancelled ? <p role="status" className={styles.warning}>취소 {cancelled}단계 · 단계 취소 기록이며 실제 모델 실행 종료 여부는 별도 확인이 필요합니다.</p> : null}
      {failed ? <p role="status" className={styles.warning}>실패 기록 {failed}단계 · 전체 단계 기록에서 해당 호출과 실패 코드를 확인하세요.</p> : null}
      {unlinked.size ? <p role="status" className={styles.warning}>부모 관계를 연결할 수 없는 단계가 있습니다. 확인되지 않은 연결선은 표시하지 않습니다.</p> : null}
      {spans.length ? <>
        <AgentFlowDiagram key={trace.run_id} flow={flow} selectedId={selected?.id} detailId={detailId} outcome={outcome}
          onSelect={spanId => setSelection({ runId: trace.run_id, spanId })} />
        <details key={`records:${trace.run_id}`} className={`${styles.content} ${styles.records}`}
          onToggle={event => setRecordsView({ runId: trace.run_id, open: event.currentTarget.open })}>
          <summary>전체 단계 기록 ({spans.length})</summary>
          <p className={styles.flowHint}>기록된 부모 관계 · 단계를 선택해 내용을 확인하세요.</p>
          {recordsView?.runId === trace.run_id && recordsView.open ? nodes(roots) : null}
          <p className={styles.muted}>막대는 관측 소요 시간 비교입니다. 중첩 단계의 시간은 합산하지 않습니다.</p>
        </details>
        {selected ? <AgentSpanModal key={`modal:${trace.run_id}`} id={detailId} span={selected}
          parent={selected.parent_id ? byId.get(selected.parent_id) : undefined}
          showCompleteBody={view === "current" || trace.content_retention === "retained"} flow={flow}
          initialSection={selection?.section}
          onSelectMaterials={spanId => setSelection({ runId: trace.run_id, spanId, section: "materials" })}
          onClose={() => setSelection(null)} /> : null}
      </> : <p className={styles.empty}>저장된 단계가 없습니다. 실행이 없었다는 의미는 아닙니다.</p>}
      <details className={styles.content}>
        <summary>실행 기록 정보</summary>
        <dl className={styles.metadata}>
          <dt>실행 ID</dt><dd className={styles.identifier}>{trace.run_id}</dd>
          <dt>revision</dt><dd>{trace.revision}</dd>
          <dt>관측 갱신</dt><dd><time dateTime={trace.updated_at}>{new Date(trace.updated_at).toLocaleString("ko-KR")}</time></dd>
          <dt>기록된 단계</dt><dd>{spans.length}개</dd>
        </dl>
      </details>
    </>}
  </section>;
}
