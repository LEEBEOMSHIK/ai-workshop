"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { AgentFlow } from "./agent-flow";
import { buildMermaidGraph, spanKindLabels } from "./mermaid-agent-graph";
import { bindMermaidGraph, type GraphController } from "./mermaid-graph-interaction";
import type { Bounds, Point } from "./mermaid-graph-geometry";
import { renderMermaid } from "./mermaid-runtime";
import { ExecutionOutcomeSummary, type ExecutionOutcome } from "./ExecutionOutcomeSummary";
import styles from "./MermaidAgentDiagram.module.css";

export function AgentFlowDiagram({ flow, selectedId, detailId, onSelect, outcome }: {
  flow: AgentFlow; selectedId?: string; detailId: string; onSelect: (id: string) => void; outcome?: ExecutionOutcome;
}) {
  const instanceId = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const hintId = useId();
  const host = useRef<HTMLDivElement>(null);
  const positions = useRef(new Map<string, Point>());
  const camera = useRef<Bounds | undefined>(undefined);
  const renderSequence = useRef(0);
  const controller = useRef<GraphController | null>(null);
  const selectRef = useRef(onSelect);
  const [rendered, setRendered] = useState<{ source: string; state: "ready" | "error" } | null>(null);
  const graph = buildMermaidGraph(flow);
  const source = graph.source;
  const state = rendered?.source === source ? rendered.state : "loading";
  const latest = useRef({ graph, flow, selectedId, detailId });
  useEffect(() => { selectRef.current = onSelect; latest.current = { graph, flow, selectedId, detailId }; });
  useEffect(() => {
    const target = host.current;
    if (!target) return;
    let disposed = false;
    delete target.dataset.renderError;
    const scratch = document.createElement("div");
    scratch.className = styles.scratch; scratch.setAttribute("aria-hidden", "true");
    document.body.append(scratch);
    // Modal selection does not replace the SVG, preserving focus and layout.
    renderMermaid(`agent-diagram-${instanceId}-${++renderSequence.current}`, source, scratch).then(({ svg }) => {
      if (disposed) return;
      target.innerHTML = svg;
      const element = target.querySelector("svg");
      if (!element) throw new Error("diagram_svg_missing");
      element.removeAttribute("width"); element.removeAttribute("height");
      element.style.maxWidth = "none";
      element.setAttribute("role", "group"); element.setAttribute("aria-label", "기록된 단계와 부모 연결");
      controller.current = bindMermaidGraph(element, latest.current.graph, positions.current, id => selectRef.current(id), camera);
      for (const node of element.querySelectorAll<SVGGElement>("[data-agent-span-id]")) {
        const span = latest.current.flow.byId.get(node.getAttribute("data-agent-span-id")!);
        if (!span) continue;
        node.setAttribute("aria-label", `${spanKindLabels[span.kind]} · ${span.name} · #${span.sequence + 1}`);
        node.setAttribute("data-kind", span.kind); node.setAttribute("data-state", span.state);
        node.setAttribute("aria-controls", latest.current.detailId);
        node.setAttribute("aria-pressed", String(span.id === latest.current.selectedId));
      }
      setRendered({ source, state: "ready" });
    }).catch((error: unknown) => {
      if (!disposed) {
        target.dataset.renderError = error instanceof Error && /^diagram_[a-z_]+$/.test(error.message) ? error.message : "diagram_render_failed";
        target.replaceChildren(); setRendered({ source, state: "error" });
      }
    }).finally(() => { scratch.remove(); });
    return () => { disposed = true; controller.current?.destroy(); controller.current = null; target.replaceChildren(); scratch.remove(); };
  }, [source, instanceId]);
  useEffect(() => {
    for (const node of host.current?.querySelectorAll("[data-agent-span-id]") ?? []) {
      node.setAttribute("aria-pressed", String(node.getAttribute("data-agent-span-id") === selectedId));
    }
  }, [selectedId]);

  return <section className={styles.diagram} aria-label="에이전트 위임 그림" aria-describedby={hintId} tabIndex={-1}>
    <div className={styles.heading}>
      <div><strong>실행 흐름</strong><span className={styles.engine}>Mermaid · {flow.ordered.length}단계</span></div>
      <div className={styles.controls} role="group" aria-label="흐름도 보기 조절">
        <button type="button" aria-label="흐름도 축소" disabled={state !== "ready"} onClick={() => controller.current?.zoom(1.25)}>−</button>
        <button type="button" aria-label="흐름도 확대" disabled={state !== "ready"} onClick={() => controller.current?.zoom(0.8)}>+</button>
        <button type="button" disabled={state !== "ready"} onClick={() => controller.current?.fit()}>전체 보기</button>
        <button type="button" disabled={state !== "ready"} onClick={() => controller.current?.reset()}>배치 초기화</button>
      </div>
    </div>
    <ExecutionOutcomeSummary outcome={outcome} />
    <p id={hintId} className={styles.hint}>클릭하면 지침·입력·결과 · 노드를 끌어 배치 변경 · 빈 공간을 끌어 이동</p>
    <div className={styles.canvas} ref={host} aria-busy={state === "loading"} />
    {state === "loading" ? <p role="status">흐름도를 그리고 있습니다.</p> : null}
    {state === "error" ? <p role="status" className={styles.error}>흐름도를 표시하지 못했습니다. 아래 전체 단계 기록에서 같은 상세 내용을 확인할 수 있습니다.</p> : null}
    <div className={styles.footer}>
      <span>연결선은 저장된 부모 관계 · 번호는 기록 순서</span>
      <details><summary>키보드 조작</summary><p>Tab으로 단계 선택 · Enter 또는 Space로 상세 열기 · 방향키로 이동 · Shift와 방향키로 크게 이동. 바꾼 배치는 이 화면에서만 유지됩니다.</p></details>
    </div>
  </section>;
}
