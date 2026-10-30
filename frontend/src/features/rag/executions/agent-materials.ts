import type { AgentFlow, AgentSpan } from "./agent-flow";
import { inspectStepContent, type StepOverview } from "./agent-step-overview";

export type RelatedMaterialStage = { span: AgentSpan; evidenceCount: number };

export function hasReadableEvidence(input: StepOverview) {
  return input.context.evidence?.some(item => {
    if (typeof item === "string") return item.trim().length > 0;
    if (!item || typeof item !== "object" || Array.isArray(item)) return false;
    const text = (item as Record<string, unknown>).text;
    return typeof text === "string" && text.trim().length > 0;
  }) ?? false;
}

function validAncestors(id: string, flow: AgentFlow): string[] | null {
  const ancestors: string[] = [];
  const seen = new Set<string>();
  let current: string | null | undefined = id;
  while (current) {
    if (seen.has(current)) return null;
    seen.add(current);
    const span = flow.byId.get(current);
    if (!span) return null;
    if (current !== id) ancestors.push(current);
    current = span.parent_id;
  }
  return ancestors;
}

export function relatedMaterialStages(id: string, flow: AgentFlow, showCompleteBody: boolean): RelatedMaterialStage[] {
  // Do not inspect text from any other span when the trace's body policy denies access.
  if (!showCompleteBody) return [];
  const ancestors = validAncestors(id, flow);
  if (!ancestors) return [];
  const related = new Set(ancestors);
  const pending = [...(flow.children.get(id) ?? [])];
  const visited = new Set([id]);
  while (pending.length) {
    const child = pending.shift()!;
    if (visited.has(child.id)) continue;
    visited.add(child.id);
    if (!validAncestors(child.id, flow)) continue;
    related.add(child.id);
    pending.push(...(flow.children.get(child.id) ?? []));
  }
  return flow.ordered.flatMap(span => {
    if (!related.has(span.id)) return [];
    const input = inspectStepContent(span.input, showCompleteBody, "input");
    return input.state === "complete" && input.context.evidenceCount && hasReadableEvidence(input)
      ? [{ span, evidenceCount: input.context.evidenceCount }] : [];
  });
}
