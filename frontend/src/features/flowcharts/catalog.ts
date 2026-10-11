import type { FlowDefinition } from "./types";

function reachable(seeds: readonly string[], adjacency: ReadonlyMap<string, readonly string[]>): Set<string> {
  const visited = new Set<string>();
  const pending = [...seeds];
  while (pending.length) {
    const id = pending.pop()!;
    if (visited.has(id)) continue;
    visited.add(id);
    pending.push(...(adjacency.get(id) ?? []));
  }
  return visited;
}

export function validateFlowCatalog(flows: readonly FlowDefinition[]): void {
  const identities = new Set<string>();
  const categories = new Map<string, string>();
  for (const flow of flows) {
    if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(flow.id) || !/^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(flow.categoryId) || !flow.categoryLabel.trim()) {
      throw new Error("flow_identity_invalid");
    }
    const identity = `${flow.categoryId}/${flow.id}`;
    if (identities.has(identity)) throw new Error("flow_identity_duplicate");
    identities.add(identity);
    if (categories.has(flow.categoryId) && categories.get(flow.categoryId) !== flow.categoryLabel) throw new Error("flow_category_conflict");
    categories.set(flow.categoryId, flow.categoryLabel);
    const nodes = new Map(flow.nodes.map(node => [node.id, node]));
    if (nodes.size !== flow.nodes.length) throw new Error("flow_node_duplicate");
    if (nodes.get(flow.entryNodeId)?.kind !== "start") throw new Error("flow_entry_invalid");
    const forward = new Map<string, string[]>();
    const reverse = new Map<string, string[]>();
    for (const edge of flow.edges) {
      if (!nodes.has(edge.from) || !nodes.has(edge.to) || !edge.condition.trim()) throw new Error("flow_edge_invalid");
      forward.set(edge.from, [...(forward.get(edge.from) ?? []), edge.to]);
      reverse.set(edge.to, [...(reverse.get(edge.to) ?? []), edge.from]);
    }
    if (reachable([flow.entryNodeId], forward).size !== nodes.size) throw new Error("flow_node_unreachable");
    const results = flow.nodes.filter(node => node.kind === "result").map(node => node.id);
    if (reachable(results, reverse).size !== nodes.size) throw new Error("flow_result_unreachable");
    const architecture = flow.architecture;
    if (!architecture || !architecture.summary.trim() ||
      !architecture.technologies.length || architecture.technologies.some(item => !item.name.trim() || !item.purpose.trim() || !item.implementation.trim()) ||
      !architecture.steps.length || architecture.steps.some(item => !item.title.trim() || !item.technology.trim() || !item.explanation.trim()) ||
      !architecture.example.question.trim() || !architecture.example.explanation.trim() ||
      (architecture.example.followup !== undefined && !architecture.example.followup.trim()) ||
      !architecture.boundaries.length || architecture.boundaries.some(item => !item.trim()) ||
      !architecture.references.length || architecture.references.some(item => !item.title.trim() || !item.reference.trim())) throw new Error("flow_architecture_invalid");
    const phaseIds = new Set<string>();
    const covered = new Set<string>();
    if (!flow.phases.length) throw new Error("flow_phase_invalid");
    for (const phase of flow.phases) {
      if (!phase.id.trim() || phaseIds.has(phase.id) || !phase.title.trim() || !phase.summary.trim() || !phase.nodeIds.length ||
        !phase.technical.components.length || phase.technical.components.some(item => !item.name.trim() || !item.role.trim()) ||
        !phase.technical.mechanism.length || phase.technical.mechanism.some(item => !item.trim()) ||
        !phase.technical.checks.length || phase.technical.checks.some(item => !item.trim()) ||
        !phase.technical.references.length || phase.technical.references.some(item => !item.title.trim() || !item.reference.trim())) throw new Error("flow_phase_invalid");
      phaseIds.add(phase.id);
      for (const id of phase.nodeIds) {
        if (!nodes.has(id) || covered.has(id)) throw new Error("flow_phase_coverage_invalid");
        covered.add(id);
      }
    }
    if (covered.size !== nodes.size) throw new Error("flow_phase_coverage_invalid");
  }
}

export function findFlow(flows: readonly FlowDefinition[], categoryId: string, flowId: string): FlowDefinition | undefined {
  return flows.find(flow => flow.categoryId === categoryId && flow.id === flowId);
}
