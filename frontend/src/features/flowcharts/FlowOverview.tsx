import type { FlowDefinition, FlowPhase } from "./types";
import styles from "./Flowcharts.module.css";

export function FlowOverview({ flow, onOpenPhase }: { flow: FlowDefinition; onOpenPhase: (phase: FlowPhase) => void }) {
  const phaseForNode = new Map(flow.phases.flatMap(phase => phase.nodeIds.map(id => [id, phase] as const)));
  return <figure className={styles.overview} aria-label={`${flow.title} 전체 흐름`}>
    <figcaption>큰 단계별 목적을 먼저 읽고, 알고 싶은 단계를 눌러 기술 상세를 확인하세요. 연결은 세부 흐름을 묶은 것이며 정확한 조건·실패·되돌림은 기술 상세에 있습니다.</figcaption>
    <ol className={styles.phaseGrid}>{flow.phases.map((phase, index) => {
      const targets = [...new Map(flow.edges.filter(edge => phase.nodeIds.includes(edge.from) && !phase.nodeIds.includes(edge.to)).map(edge => {
        const target = phaseForNode.get(edge.to)!;
        return [target.id, target] as const;
      })).values()];
      return <li key={phase.id} className={styles.phaseCard}>
        <p className={styles.eyebrow}>큰 단계 {index + 1}</p>
        <button type="button" className={styles.phaseButton} aria-label={`${phase.title} 기술 상세 보기`} onClick={() => onOpenPhase(phase)}><strong>{phase.title}</strong><span>{phase.summary}</span><small>세부 {phase.nodeIds.length}단계 · 기술 상세 보기 ↗</small></button>
        {targets.length > 0 && <ul className={styles.phaseConnections} aria-label={`${phase.title} 큰 단계 연결`}>{targets.map(target => <li key={target.id}>→ {target.title}</li>)}</ul>}
      </li>;
    })}</ol>
  </figure>;
}
