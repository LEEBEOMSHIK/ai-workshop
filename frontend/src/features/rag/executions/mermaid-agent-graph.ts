import type { AgentFlow, AgentSpan } from "./agent-flow";

export const spanKindLabels: Record<AgentSpan["kind"], string> = {
  agent: "에이전트", model: "모델 호출", delegation: "위임", tool: "도구",
};
export const spanStateLabels: Record<AgentSpan["state"], string> = {
  running: "진행 중", completed: "처리 완료", failed: "실패", cancelled: "취소",
};
export type GraphNode = { key: string; spanId: string; label: string };
export type GraphEdge = { key: string; sourceId: string; targetId: string };
export type MermaidAgentGraph = { source: string; nodes: GraphNode[]; edges: GraphEdge[] };

// Quoted text cannot escape into Mermaid grammar. Display-only punctuation uses
// full-width forms; exact stored names remain available in the modal and ARIA label.
// Numeric HTML entities are deliberately avoided: SVG text renders them literally.
export function encodeMermaidLabel(value: string) {
  return value.replace(/[<>"&\[\]{}\\`#%;]/g, character => String.fromCharCode(character.charCodeAt(0) + 0xfee0))
    .replace(/[\r\n\t]/g, " ");
}

export function buildMermaidGraph(flow: AgentFlow): MermaidAgentGraph {
  const nodes = flow.ordered.map((span, index) => ({
    key: `n${index}`, spanId: span.id,
    label: `${span.sequence + 1} · ${spanKindLabels[span.kind]}\n${(span.name.length > 64 ? `${span.name.slice(0,64)}…` : span.name).replace(/[\r\n]/g, " ")}\n${spanStateLabels[span.state]}`,
  }));
  const byId = new Map(nodes.map(node => [node.spanId, node]));
  const edges: GraphEdge[] = [];
  for (const [sourceId, children] of flow.children) {
    for (const child of children) edges.push({ key: `e${edges.length}`, sourceId, targetId: child.id });
  }
  const source = ["flowchart LR",
    ...nodes.map(node => `${node.key}["${node.label.split("\n").map(encodeMermaidLabel).join("<br/>")}"]:::${flow.byId.get(node.spanId)!.kind}_${flow.byId.get(node.spanId)!.state}`),
    ...edges.map(edge => `${byId.get(edge.sourceId)!.key} ${edge.key}@--> ${byId.get(edge.targetId)!.key}`),
  ].join("\n");
  return { source, nodes, edges };
}
