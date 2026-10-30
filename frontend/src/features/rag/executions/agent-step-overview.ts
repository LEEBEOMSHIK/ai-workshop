import type { components } from "../../../shared/api/schema";

type AgentContent = components["schemas"]["AgentContent"];
export type StepOverview = {
  state: AgentContent["content_status"] | "missing";
  kind: "request" | "answer" | "tool_request" | "refusal" | "value" | "unknown";
  items: { label: string; text: string }[];
  note?: string;
  limited: boolean;
  context: {
    instructions: { role: string; text: string }[];
    history?: unknown[];
    evidence?: unknown[];
    evidenceCount?: number;
    availableEvidence?: string;
    rewrittenQuery?: string;
  };
};

const MAX_DEPTH = 12;
const MAX_ITEMS = 40;
const MAX_CHARACTERS = 32768;

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function scalar(value: unknown): string | undefined {
  if (typeof value === "string") return value === "" ? '""' : value;
  if (value === null || typeof value === "boolean" || typeof value === "number") return String(value);
  return undefined;
}

function decode(value: unknown): unknown {
  if (typeof value !== "string" || value.length > MAX_CHARACTERS) return value;
  try { return JSON.parse(value) as unknown; } catch { return value; }
}

function bounded(items: unknown[], result: StepOverview) {
  if (items.length > MAX_ITEMS) result.limited = true;
  return items.slice(0, MAX_ITEMS);
}

function note(result: StepOverview, message: string) {
  if (!result.note?.includes(message)) result.note = result.note ? `${result.note} ${message}` : message;
}

function collectContext(value: Record<string, unknown>, result: StepOverview) {
  const context = result.context;
  if (Array.isArray(value.history)) {
    context.history = bounded(value.history, result);
    // The exact original remains available when only a prefix is projected.
  }
  if (Array.isArray(value.evidence)) {
    context.evidence = bounded(value.evidence, result);
    context.evidenceCount = value.evidence.length;
  } else if (Array.isArray(value.evidence_blocks)) {
    const blocks = value.evidence_blocks;
    const valid = blocks.every(block => record(block) && Array.isArray(block.fragments));
    if (valid) {
      const fragments = blocks.flatMap(block => (block as { fragments: unknown[] }).fragments);
      context.evidence = bounded(fragments, result);
      context.evidenceCount = fragments.length;
    }
  }
  if (Object.hasOwn(value, "available_evidence_count")) context.availableEvidence = scalar(value.available_evidence_count);
  if (typeof value.resolved_query === "string" && value.resolved_query !== value.question) context.rewrittenQuery = value.resolved_query;
}

function collectMessages(messages: unknown[], result: StepOverview) {
  const allowed = bounded(messages, result);
  result.context.instructions.push(...allowed.flatMap(message =>
    record(message) && (message.role === "system" || message.role === "developer") && typeof message.content === "string"
      ? [{ role: message.role, text: message.content }] : [],
  ));
}

function lastMessage(messages: unknown[], role: string) {
  for (let index = messages.length - 1; index >= 0; index--) {
    const message = messages[index];
    if (record(message) && message.role === role) return message;
  }
  return undefined;
}

function readInput(value: unknown, result: StepOverview, depth: number): void {
  if (depth >= MAX_DEPTH) { result.limited = true; return; }
  const decoded = decode(value);
  if (decoded !== value) { readInput(decoded, result, depth + 1); return; }
  const text = scalar(value);
  if (text !== undefined) {
    result.kind = "value"; result.items.push({ label: "기록된 입력", text }); return;
  }
  if (Array.isArray(value)) { readMessageInput(value, result, depth); return; }
  if (!record(value)) return;
  collectContext(value, result);
  if (Array.isArray(value.messages)) collectMessages(value.messages, result);
  // Root fields have precedence. History/evidence/tool schemas are never searched for a question.
  const question = Object.hasOwn(value, "question") ? scalar(value.question) : undefined;
  const task = Object.hasOwn(value, "delegated_task") ? scalar(value.delegated_task)
    : Object.hasOwn(value, "task") ? scalar(value.task) : undefined;
  if (question !== undefined) result.items.push({ label: "질문", text: question });
  if (task !== undefined && task !== question) result.items.push({ label: Object.hasOwn(value, "delegated_task") ? "위임된 작업" : "작업 요청", text: task });
  if (result.items.length) { result.kind = "request"; return; }
  if (Array.isArray(value.messages)) { readMessageInput(value.messages, result, depth, false); return; }
  if (Object.hasOwn(value, "arguments")) { readInput(value.arguments, result, depth + 1); return; }
  if (Object.hasOwn(value, "content")) { readInput(value.content, result, depth + 1); return; }
  if (typeof value.resolved_query === "string") {
    result.kind = "request"; result.items.push({ label: "재작성 검색 질의", text: value.resolved_query });
  }
}

function readMessageInput(messages: unknown[], result: StepOverview, depth: number, collect = true) {
  if (collect) collectMessages(messages, result);
  // Only a recorded user message can supply the request, never system/developer instructions.
  const lastUser = lastMessage(messages, "user");
  if (record(lastUser) && Object.hasOwn(lastUser, "content")) readInput(lastUser.content, result, depth + 1);
}

function readTool(name: unknown, argumentsValue: unknown, result: StepOverview, depth: number) {
  result.kind = "tool_request";
  result.items.push({ label: "호출 도구", text: typeof name === "string" ? name : "도구 이름 미기록" });
  const request: StepOverview = { state: "complete", kind: "unknown", items: [], limited: false, context: { instructions: [] } };
  readInput(argumentsValue, request, depth + 1);
  result.items.push(...request.items.map(item => ({ label: request.kind === "value" ? "기록된 도구 인자" : "요청한 작업", text: item.text })));
  if (!request.items.length) note(result, "도구 인자를 핵심 항목으로 구분하지 못했습니다. 원문·기술 기록에서 전체 인자를 확인하세요.");
  result.limited ||= request.limited;
}

function readOutput(value: unknown, result: StepOverview, depth: number): void {
  if (depth >= MAX_DEPTH) { result.limited = true; return; }
  const decoded = decode(value);
  if (decoded !== value) { readOutput(decoded, result, depth + 1); return; }
  const text = scalar(value);
  if (text !== undefined) { result.kind = "value"; result.items.push({ label: "기록된 반환값", text }); return; }
  if (Array.isArray(value)) {
    const lastAssistant = lastMessage(value, "assistant");
    if (lastAssistant) readOutput(lastAssistant, result, depth + 1);
    return;
  }
  if (!record(value)) return;
  if (Object.hasOwn(value, "tool") && Object.hasOwn(value, "arguments")) {
    readTool(value.tool, value.arguments, result, depth); return;
  }
  if (Array.isArray(value.tool_calls)) {
    for (const call of bounded(value.tool_calls, result)) {
      if (record(call) && record(call.function)) readTool(call.function.name, call.function.arguments, result, depth);
      else note(result, "일부 도구 호출 항목을 구분하지 못했습니다. 원문·기술 기록에서 전체 반환값을 확인하세요.");
    }
    if (result.items.length) {
      if (typeof value.content === "string" && value.content) result.items.push({ label: "함께 반환된 내용", text: value.content });
      return;
    }
  }
  if (Array.isArray(value.claims)) {
    result.kind = "answer";
    for (const claim of bounded(value.claims, result)) {
      if (record(claim) && typeof claim.text === "string") result.items.push({ label: "답변 내용", text: claim.text === "" ? '""' : claim.text });
      else note(result, "일부 주장 항목의 본문을 구분하지 못했습니다. 원문·기술 기록에서 전체 반환값을 확인하세요.");
    }
    if (value.claims.length === 0) result.note = "답변 주장 0개가 기록되었습니다.";
  }
  if (value.status === "insufficient_evidence") {
    result.kind = "refusal"; note(result, "근거 부족 응답이 기록되었습니다 (insufficient_evidence)."); return;
  }
  if (result.kind === "answer") return;
  if (Array.isArray(value.messages)) { readOutput(value.messages, result, depth + 1); return; }
  if (Object.hasOwn(value, "content")) { readOutput(value.content, result, depth + 1); return; }
  if (typeof value.text === "string") { result.kind = "value"; result.items.push({ label: "기록된 반환값", text: value.text || '""' }); }
}

export function inspectStepContent(content: AgentContent | undefined, showCompleteBody: boolean, purpose: "input" | "output"): StepOverview {
  const state = content?.content_status === "complete" && !showCompleteBody ? "not_retained" : content?.content_status ?? "missing";
  const result: StepOverview = { state, kind: "unknown", items: [], limited: false, context: { instructions: [] } };
  // Policy is evaluated before reading/parsing the body. Denied content never enters this projection.
  if (state !== "complete") return result;
  if (content?.text == null) {
    result.note = "확인 가능한 본문이 없습니다. 원문·기술 기록에서 개별 보관 상태를 확인하세요.";
    return result;
  }
  if (content.text.length > MAX_CHARACTERS) result.limited = true;
  else (purpose === "input" ? readInput : readOutput)(content.text, result, 0);
  if (!result.items.length && !result.note) result.note = "핵심 내용을 구분할 수 없는 형식입니다. 원문·기술 기록에서 확인하세요.";
  return result;
}
