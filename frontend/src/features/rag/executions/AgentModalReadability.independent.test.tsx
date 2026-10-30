import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { AgentSpanModal } from "./AgentSpanModal";
import { AgentStepMaterials } from "./AgentStepOverview";
import { buildAgentFlow } from "./agent-flow";
import { inspectStepContent } from "./agent-step-overview";
import { syntheticAgentTrace, syntheticContent } from "./agent-trace.test-support";

it("never reads the body property when overview policy withholds it", () => {
  for (const state of ["complete", "not_retained", "disabled", "not_applicable", "omitted_size_limit", "omitted_validation_failure"] as const) {
    const readBody = vi.fn(() => { throw new Error("SYNTHETIC_DENIED_BODY_ACCESSED"); });
    const content = { ...syntheticContent(""), content_status: state };
    Object.defineProperty(content, "text", { get: readBody });
    for (const purpose of ["input", "output"] as const) {
      const result = inspectStepContent(content, state !== "complete", purpose);
      expect(result.items).toEqual([]);
      expect(result.context).toEqual({ instructions: [] });
    }
    expect(readBody).not.toHaveBeenCalled();
  }
});

it("marks a partial observed answer when unrecognized claims are omitted", () => {
  const content = syntheticContent(JSON.stringify({ status: "answered", claims: [
    { text: "SYNTHETIC_VALID_CLAIM" },
    { unexpected_body: "SYNTHETIC_UNRECOGNIZED_CLAIM" },
  ] }));
  const result = inspectStepContent(content, true, "output");
  expect(result.items).toContainEqual({ label: "답변 내용", text: "SYNTHETIC_VALID_CLAIM" });
  expect(result.items.some(item => item.text === "SYNTHETIC_UNRECOGNIZED_CLAIM")).toBe(false);
  expect(result.limited || Boolean(result.note)).toBe(true);
});

it("marks an unrecognized tool argument instead of silently showing only its tool name", () => {
  const content = syntheticContent(JSON.stringify({ tool: "synthetic_custom_tool",
    arguments: { unsupported_request: { enabled: false, limit: 0 } },
  }));
  const result = inspectStepContent(content, true, "output");
  expect(result.kind).toBe("tool_request");
  expect(result.items).toContainEqual({ label: "호출 도구", text: "synthetic_custom_tool" });
  expect(result.limited || Boolean(result.note)).toBe(true);
});

it("preserves the speakers of displayed conversation history", async () => {
  const input = inspectStepContent(syntheticContent(JSON.stringify({ question: "합성 현재 요청", history: [
    { role: "user", content: "합성 첫 번째 발화" },
    { role: "assistant", content: "합성 두 번째 발화" },
  ] })), true, "input");
  render(<AgentStepMaterials input={input} />);
  await userEvent.click(screen.getByText("함께 전달된 자료", { selector: "summary" }));
  expect(screen.getByText("합성 첫 번째 발화")).toBeVisible();
  expect(screen.getByText("합성 두 번째 발화")).toBeVisible();
  expect(screen.getByText(/사용자|user/)).toBeVisible();
  expect(screen.getByText(/어시스턴트|assistant/)).toBeVisible();
});

it("keeps long input exact in raw details and removes both overview and raw content when access changes", async () => {
  const trace = syntheticAgentTrace();
  const question = `SYNTHETIC_LONG_QUESTION_${"가".repeat(1400)}`;
  const raw = JSON.stringify({ question, history: [], available_evidence_count: 0 });
  const span = { ...trace.spans[0], input: syntheticContent(raw) };
  const flow = buildAgentFlow([span, ...trace.spans.slice(1)]);
  const view = render(<AgentSpanModal span={span} flow={flow} showCompleteBody onClose={vi.fn()} />);
  const request = within(screen.getByRole("region", { name: "받은 요청" }));
  expect(request.getByText(/앞부분.*600자/)).toBeVisible();
  expect(screen.queryByLabelText("전달 입력 원문")).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("원문·기술 기록", { selector: "summary" }));
  const input = within(screen.getByRole("region", { name: "전달 입력" }));
  await userEvent.click(input.getByText("원문 펼치기", { selector: "summary" }));
  expect(input.getByLabelText("전달 입력 원문").textContent).toBe(raw);
  expect(span.input.text).toBe(raw);
  view.rerender(<AgentSpanModal span={span} flow={flow} showCompleteBody={false} onClose={vi.fn()} />);
  expect(document.body.textContent).not.toContain("SYNTHETIC_LONG_QUESTION_");
  expect(screen.queryByLabelText("전달 입력 원문")).not.toBeInTheDocument();
  expect(screen.getAllByText("당시 본문 미보관").length).toBeGreaterThan(0);
});
