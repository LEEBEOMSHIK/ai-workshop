import { inspectStepContent } from "./agent-step-overview";
import { syntheticContent } from "./agent-trace.test-support";

function inspect(value: unknown, purpose: "input" | "output" = "input") {
  return inspectStepContent(syntheticContent(JSON.stringify(value)), true, purpose);
}

it("prioritizes the actual question and preserves distinct rewritten and delegated requests without duplicate questions", () => {
  const result = inspect({ question: "합성 현재 질문", resolved_query: "합성 독립 검색어", delegated_task: "합성 위임 작업",
    history: [{ role: "user", content: "이전 대화", question: "승격하면 안 되는 이전 질문" }],
    evidence: [{ text: "합성 근거", question: "승격하면 안 되는 근거 질문", claims: [{ text: "거짓 답변" }] }] });
  expect(result.items).toEqual([{ label: "질문", text: "합성 현재 질문" }, { label: "위임된 작업", text: "합성 위임 작업" }]);
  expect(result.context.rewrittenQuery).toBe("합성 독립 검색어");
  expect(result.context.history).toHaveLength(1);
  expect(result.context.evidenceCount).toBe(1);
  expect(inspect({ question: "같은 질문", resolved_query: "같은 질문", delegated_task: "같은 질문" }).items).toEqual([{ label: "질문", text: "같은 질문" }]);
});

it("reads the last user message while keeping system and developer instructions out of the primary request", () => {
  const result = inspect({ messages: [
    { role: "system", content: "Synthetic long system instructions" },
    { role: "developer", content: "Synthetic developer instructions" },
    { role: "user", content: "합성 이전 사용자 메시지" },
    { role: "assistant", content: "합성 이전 답변" },
    { role: "user", content: JSON.stringify({ question: "합성 현재 질문", history: [], available_evidence_count: 28 }) },
  ], tools: [{ function: { name: "unused_tool", description: "사용 가능한 도구" } }] });
  expect(result.items).toEqual([{ label: "질문", text: "합성 현재 질문" }]);
  expect(result.context.instructions).toEqual([
    { role: "system", text: "Synthetic long system instructions" },
    { role: "developer", text: "Synthetic developer instructions" },
  ]);
  expect(result.context.availableEvidence).toBe("28");
  expect(result.context.evidenceCount).toBeUndefined();
});

it.each([JSON.stringify({ task: "합성 도구 작업" }), { task: "합성 도구 작업" }])(
  "labels canonical tool returns with either encoded or object arguments as tool requests", argumentsValue => {
    const result = inspect({ tool: "synthetic_tool", arguments: argumentsValue }, "output");
    expect(result.kind).toBe("tool_request");
    expect(result.items).toEqual([{ label: "호출 도구", text: "synthetic_tool" }, { label: "요청한 작업", text: "합성 도구 작업" }]);
  },
);

it("reads tool_calls as tool requests without presenting their task as an answer", () => {
  const result = inspect({ role: "assistant", tool_calls: [{ type: "function", function: {
    name: "synthetic_function", arguments: '{"task":"합성 후속 작업"}',
  } }] }, "output");
  expect(result.kind).toBe("tool_request");
  expect(result.items).toContainEqual({ label: "요청한 작업", text: "합성 후속 작업" });
  expect(result.items.some(item => item.label === "답변 내용")).toBe(false);
});

it("extracts only direct answer claims and preserves an explicit insufficient-evidence response", () => {
  const answer = inspect({ status: "answered", claims: [{ text: "합성 첫 주장", evidence_ids: ["synthetic-uuid"] }, { text: "합성 둘째 주장" }] }, "output");
  expect(answer.kind).toBe("answer");
  expect(answer.items.map(item => item.text)).toEqual(["합성 첫 주장", "합성 둘째 주장"]);
  expect(JSON.stringify(answer.items)).not.toContain("synthetic-uuid");
  const refusal = inspect({ status: "insufficient_evidence", claims: [] }, "output");
  expect(refusal.kind).toBe("refusal");
  expect(refusal.note).toContain("insufficient_evidence");
  expect(refusal.note).not.toContain("미기록");
  expect(inspect({ evidence: [{ claims: [{ text: "근거 속 주장" }] }] }, "output").items).toEqual([]);
});

it("flags partial claim and tool argument projections instead of silently hiding unknown return fields", () => {
  const claims = inspect({ claims: [{ text: "표시 가능한 합성 주장" }, { unsupported: "원문에만 있는 반환 항목" }] }, "output");
  expect(claims.items.map(item => item.text)).toEqual(["표시 가능한 합성 주장"]);
  expect(claims.note).toMatch(/일부.*주장.*원문/);
  const tool = inspect({ tool: "synthetic_tool", arguments: { unsupported: "알 수 없는 인자" } }, "output");
  expect(tool.kind).toBe("tool_request");
  expect(tool.note).toMatch(/도구 인자.*원문/);
  const mixed = inspect({ tool_calls: [{ function: { name: "known", arguments: '{"task":"합성 작업"}' } }, { unsupported: "호출 미상" }] }, "output");
  expect(mixed.note).toMatch(/일부.*도구 호출.*원문/);
});

it("counts actual compact fragments separately from available evidence and ignores unrelated references", () => {
  const result = inspect({ question: "합성 질문", available_evidence_count: 28,
    evidence_blocks: [{ source_ref: 0, fragments: [{ text: "첫 근거" }, { text: "둘째 근거" }] }] });
  expect(result.context.availableEvidence).toBe("28");
  expect(result.context.evidenceCount).toBe(2);
  expect(result.context.evidence).toEqual([{ text: "첫 근거" }, { text: "둘째 근거" }]);
  expect(inspect({ question: "합성 질문", available_evidence_count: 0 }).context.evidenceCount).toBeUndefined();
  expect(inspect({ question: "합성 질문", evidence: [] }).context.evidenceCount).toBe(0);
});

it.each([0, false, null, ""])("preserves the explicit scalar %j and plain text without inventing missing content", value => {
  const result = inspect(value, "output");
  expect(result.state).toBe("complete");
  expect(result.kind).toBe("value");
  expect(result.items[0].text).toBe(value === "" ? '""' : String(value));
});

it.each([null, undefined])("explains an absent complete body (%j) without confusing it with the recorded JSON null value", text => {
  const result = inspectStepContent({ ...syntheticContent("ignored"), text }, true, "output");
  expect(result.state).toBe("complete");
  expect(result.items).toEqual([]);
  expect(result.note).toMatch(/확인 가능한 본문.*없/);
  expect(inspect(null, "output").items).toEqual([{ label: "기록된 반환값", text: "null" }]);
});

it("keeps plain text as observed content and unknown JSON out of the primary summary", () => {
  const text = inspectStepContent(syntheticContent("합성 일반 입력"), true, "input");
  expect(text.items).toEqual([{ label: "기록된 입력", text: "합성 일반 입력" }]);
  const unknown = inspect({ unsupported: { question: "승격하면 안 되는 질문" }, schema_version: 2 });
  expect(unknown.kind).toBe("unknown");
  expect(unknown.items).toEqual([]);
  expect(unknown.note).toContain("원문");
});

it("withholds content before extracting fields or retaining context", () => {
  const hidden = syntheticContent('{"question":"SYNTHETIC_SECRET","history":[{"content":"SECRET_HISTORY"}]}');
  for (const result of [inspectStepContent(hidden, false, "input"),
    inspectStepContent({ ...hidden, content_status: "omitted_validation_failure" }, true, "output")]) {
    expect(result.items).toEqual([]);
    expect(JSON.stringify(result)).not.toContain("SECRET");
    expect(result.context.instructions).toEqual([]);
  }
});

it("bounds supported wrapper depth and long collections and marks the limited projection", () => {
  let value: unknown = { question: "합성 깊은 질문" };
  for (let index = 0; index < 80; index++) value = { content: value };
  expect(inspect(value).limited).toBe(true);
  const result = inspect({ claims: Array.from({ length: 80 }, (_, index) => ({ text: `합성 주장 ${index}` })) }, "output");
  expect(result.limited).toBe(true);
  expect(result.items.length).toBeLessThan(80);
  expect(result.items[0].text).toBe("합성 주장 0");
});
