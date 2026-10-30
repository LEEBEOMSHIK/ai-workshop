import type { components } from "../../../shared/api/schema";

export type AgentSpan = components["schemas"]["AgentSpan"];
export type AgentLink = { sourceId: string; targetId: string; delegations: AgentSpan[] };
export type ObservedAgent = {
  span: AgentSpan; incoming?: AgentLink; outgoing: AgentLink[];
  models: AgentSpan[]; tools: AgentSpan[]; roles: string[];
};

export function buildSpanHierarchy(spans: AgentSpan[]) {
  const ordered = [...spans].sort((a, b) => a.sequence - b.sequence);
  const byId = new Map(ordered.map(span => [span.id, span]));
  const children = new Map<string, AgentSpan[]>();
  const roots: AgentSpan[] = [];
  const unlinked = new Set<string>();
  for (const span of ordered) {
    const seen = new Set([span.id]);
    let ancestor = span.parent_id;
    while (ancestor && byId.has(ancestor)) {
      if (seen.has(ancestor)) { unlinked.add(span.id); break; }
      seen.add(ancestor); ancestor = byId.get(ancestor)?.parent_id ?? null;
    }
    if (span.parent_id && !byId.has(span.parent_id)) unlinked.add(span.id);
    if (!span.parent_id || unlinked.has(span.id)) roots.push(span);
    else children.set(span.parent_id, [...(children.get(span.parent_id) ?? []), span]);
  }
  return { byId, children, roots, unlinked, ordered };
}

export function buildAgentFlow(spans: AgentSpan[]) {
  const hierarchy = buildSpanHierarchy(spans);
  const agents: ObservedAgent[] = hierarchy.ordered.filter(span => span.kind === "agent")
    .map(span => ({ span, outgoing: [], models: [], tools: [], roles: [] }));
  const byAgentId = new Map(agents.map(agent => [agent.span.id, agent]));

  function ancestorAgent(span: AgentSpan) {
    const seen = new Set([span.id]);
    const path: AgentSpan[] = [];
    let id = span.parent_id;
    while (id && !seen.has(id)) {
      seen.add(id);
      const parent = hierarchy.byId.get(id);
      if (!parent) return null;
      if (parent.kind === "agent") return { agent: byAgentId.get(parent.id)!, path };
      path.push(parent); id = parent.parent_id;
    }
    return null;
  }

  for (const agent of agents) {
    if (hierarchy.unlinked.has(agent.span.id)) continue;
    const parent = ancestorAgent(agent.span);
    if (!parent) continue;
    const link = { sourceId: parent.agent.span.id, targetId: agent.span.id,
      delegations: parent.path.filter(span => span.kind === "delegation").reverse() };
    agent.incoming = link;
    parent.agent.outgoing.push(link);
  }
  for (const span of hierarchy.ordered) {
    if (span.kind !== "model" && span.kind !== "tool") continue;
    const parent = ancestorAgent(span);
    if (parent) parent.agent[span.kind === "model" ? "models" : "tools"].push(span);
  }
  for (const agent of agents) {
    agent.roles.push(agent.incoming
      ? agent.incoming.delegations.length ? "위임 요청 대상" : "하위 에이전트 실행"
      : agent.span.parent_id ? "상위 관계 미기록" : "시작 에이전트");
    if (agent.outgoing.some(link => link.delegations.length)) agent.roles.push("위임 요청");
  }
  return { ...hierarchy, agents, byAgentId, agentRoots: agents.filter(agent => !agent.incoming) };
}

export type AgentFlow = ReturnType<typeof buildAgentFlow>;

export function observedModels(agent: ObservedAgent) {
  if (!agent.models.length) return "모델 호출 기록 없음";
  const names = [...new Set(agent.models.map(model => model.model_name ?? "모델명 미기록"))];
  return names.join(" · ");
}
