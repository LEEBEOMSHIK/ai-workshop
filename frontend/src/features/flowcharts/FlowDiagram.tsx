import type { FlowDefinition, FlowNode } from "./types";
import styles from "./Flowcharts.module.css";

const kindLabels: Record<FlowNode["kind"], string> = { start: "시작", action: "처리", decision: "분기", result: "결과" };

export function FlowDiagram({ flow, selectedNodeId, onSelectNode }: {
  flow: FlowDefinition; selectedNodeId: string; onSelectNode: (nodeId: string) => void;
}) {
  const targets = new Map(flow.nodes.map(node => [node.id, node.label]));
  const positions = new Map(flow.nodes.map((node, index) => [node.id, index]));
  return <figure className={styles.diagram} aria-label={`${flow.title} 처리 흐름`}>
    <figcaption>단계를 선택하면 설명을 볼 수 있습니다. 화살표의 조건을 따라 다음 단계로 이동하세요.</figcaption>
    <ol className={styles.nodes}>{flow.nodes.map((node, index) => {
      const edges = flow.edges.filter(edge => edge.from === node.id);
      return <li className={styles.nodeRow} key={node.id}>
        <button type="button" className={`${styles.node} ${styles[node.kind]}`} aria-label={`${node.label} 단계`} aria-pressed={selectedNodeId === node.id} onClick={() => onSelectNode(node.id)}>
          <span className={styles.nodeNumber} aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
          <span><small>{kindLabels[node.kind]}</small><strong>{node.label}</strong></span>
        </button>
        {edges.length > 0 ? <ul className={styles.edges} aria-label={`${node.label} 다음 조건`}>{edges.map((edge, edgeIndex) =>
          <li key={edgeIndex}><span className={styles.arrow} aria-hidden="true">{positions.get(edge.to)! <= index ? "↶" : "↓"}</span>
            <button type="button" aria-label={`${edge.condition} → ${targets.get(edge.to)}`} onClick={() => onSelectNode(edge.to)}>
              <span>{edge.condition}</span><small>→ {targets.get(edge.to)}</small>
            </button>
          </li>)}</ul> : <p className={styles.end}>이 경로 종료</p>}
      </li>;
    })}</ol>
  </figure>;
}
