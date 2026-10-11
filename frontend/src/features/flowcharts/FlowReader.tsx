"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import type { FlowDefinition, FlowPhase } from "./types";
import { FlowDiagram } from "./FlowDiagram";
import { FlowOverview } from "./FlowOverview";
import { FlowArchitectureView } from "./FlowArchitectureView";
import styles from "./Flowcharts.module.css";

export function FlowReader({ flow }: { flow: FlowDefinition }) {
  const [selectedNodeId, selectNode] = useState(flow.entryNodeId);
  const [view, setView] = useState<"overview" | "technical">("overview");
  const [returnToStep, setReturnToStep] = useState(false);
  const [showSteps, setShowSteps] = useState(false);
  const focusPhase = useRef(false);
  const detail = useRef<HTMLElement>(null);
  const diagram = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const node = flow.nodes.find(item => item.id === selectedNodeId)!;
  const phase = flow.phases.find(item => item.nodeIds.includes(selectedNodeId))!;
  function scrollBehavior(): ScrollBehavior {
    return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
  }
  function selectStep(id: string) {
    selectNode(id);
    const region = detail.current;
    if (!region) return;
    const bounds = region.getBoundingClientRect();
    const offscreen = bounds.bottom < 0 || bounds.top >= window.innerHeight;
    setReturnToStep(offscreen);
    if (offscreen) {
      region.focus({ preventScroll: true });
      region.scrollIntoView?.({ block: "start", behavior: scrollBehavior() });
    }
  }
  function returnToSelectedStep() {
    const step = diagram.current?.querySelector<HTMLButtonElement>('button[aria-pressed="true"]');
    step?.focus({ preventScroll: true });
    step?.scrollIntoView?.({ block: "center", behavior: scrollBehavior() });
    setReturnToStep(false);
  }
  function openPhase(target: FlowPhase) {
    focusPhase.current = true;
    selectNode(target.nodeIds[0]);
    setReturnToStep(true);
    setShowSteps(true);
    setView("technical");
  }
  useEffect(() => {
    if (!focusPhase.current || view !== "technical" || !detail.current) return;
    focusPhase.current = false;
    const region = detail.current;
    region.focus({ preventScroll: true });
    const bounds = region.getBoundingClientRect();
    if (bounds.bottom < 0 || bounds.top >= window.innerHeight) region.scrollIntoView?.({ block: "start", behavior: scrollBehavior() });
  }, [view, selectedNodeId]);
  return <article className={styles.reader} aria-labelledby={titleId}>
    <header className={styles.flowHeader}>
      <p className={styles.eyebrow}>{flow.categoryLabel} / 처리 흐름 설명</p><h2 id={titleId}>{flow.title}</h2>
      <p>{flow.summary}</p><p className={styles.metadata}>구현 검토 기준 {flow.reviewedAt} · 설명 v{flow.version}</p>
    </header>
    <div className={styles.viewSwitch} role="group" aria-label="설명 깊이 선택">
      <button type="button" aria-pressed={view === "overview"} onClick={() => setView("overview")}>전체 흐름</button>
      <button type="button" aria-pressed={view === "technical"} onClick={() => setView("technical")}>기술 상세</button>
    </div>
    <p className={styles.viewHelp}>{view === "overview" ? "무엇을 어떤 순서로 처리하는지 큰틀을 확인합니다." : "사용 기술의 역할과 연결 구조를 구성도·예시로 읽고, 필요한 세부 흐름을 펼쳐 보세요."}</p>
    {view === "overview" ? <FlowOverview flow={flow} onOpenPhase={openPhase} /> : <>
      <FlowArchitectureView title={flow.title} architecture={flow.architecture} />
      <details className={styles.processingDetails} open={showSteps} onToggle={event => setShowSteps(event.currentTarget.open)}>
      <summary>세부 처리·예외 흐름 보기</summary>
      {showSteps && <div className={styles.readerLayout}>
      <div ref={diagram} className={styles.diagramFrame}><FlowDiagram flow={flow} selectedNodeId={selectedNodeId} onSelectNode={selectStep} /></div>
      <section ref={detail} className={styles.detail} aria-label="단계 설명" aria-live="polite" tabIndex={-1}>
        <p className={styles.eyebrow}>선택한 단계</p><h3>{node.label}</h3>
        <dl><div><dt>입력</dt><dd>{node.input}</dd></div><div><dt>처리</dt><dd>{node.process}</dd></div><div><dt>결과</dt><dd>{node.output}</dd></div></dl>
        <section className={styles.technical} aria-label="기술 설명">
          <p className={styles.eyebrow}>큰틀과 연결 · {phase.title}</p>
          <h4>어떤 기술을 쓰나요?</h4>
          <dl>{phase.technical.components.map(component => <div key={component.name}><dt>{component.name}</dt><dd>{component.role}</dd></div>)}</dl>
          <h4>어떻게 작동하나요?</h4><ol>{phase.technical.mechanism.map(item => <li key={item}>{item}</li>)}</ol>
          <h4>확인할 지점</h4><ul>{phase.technical.checks.map(item => <li key={item}>{item}</li>)}</ul>
          <details><summary>구현 근거</summary><ul>{phase.technical.references.map(source => <li key={source.reference}><span>{source.title}</span><code>{source.reference}</code></li>)}</ul></details>
        </section>
        {node.failures.length > 0 && <div className={styles.conditions}><h4>주의·실패 조건</h4><ul>{node.failures.map(item => <li key={item}>{item}</li>)}</ul></div>}
        {returnToStep && <button type="button" className={styles.returnStep} onClick={returnToSelectedStep}>선택 단계로 돌아가기</button>}
      </section>
    </div>}
    </details></>}
    <details className={styles.textFlow}><summary>텍스트로 흐름 읽기</summary>
      <ol>{flow.nodes.map(item => <li key={item.id}><strong>{item.label}</strong><p>{item.process}</p>
        <ul>{flow.edges.filter(edge => edge.from === item.id).map((edge, index) => <li key={index}>{edge.condition} → {flow.nodes.find(target => target.id === edge.to)!.label}</li>)}</ul>
      </li>)}</ol>
    </details>
    <footer className={styles.footer}>
      {flow.links.length > 0 && <nav aria-label="관련 화면">{flow.links.map(link => <Link key={link.href} href={link.href}>{link.label}<span aria-hidden="true"> ↗</span></Link>)}</nav>}
      <p className={styles.sources}>설명 근거: {flow.sources.map((source, index) => <span key={source.reference}>{index > 0 && <span aria-hidden="true"> · </span>}<span>{source.title}</span></span>)}</p>
    </footer>
  </article>;
}
