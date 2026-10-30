import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { AgentTracePanel } from "./AgentTracePanel";
import type { AgentFlow } from "./agent-flow";
import { syntheticContent, syntheticSteppedAgentTrace } from "./agent-trace.test-support";

// Keep the real panel, modal, content policy and material navigation together.
// Only Mermaid layout is replaced; the main reviewer verifies the actual SVG in Chrome.
vi.mock("./AgentFlowDiagram", () => ({
  AgentFlowDiagram: ({ flow, selectedId, onSelect }: {
    flow: AgentFlow; selectedId?: string; onSelect: (spanId: string) => void;
  }) => <section aria-label="에이전트 위임 그림">
    {flow.ordered.map(span => <button key={span.id} type="button" data-agent-span-id={span.id}
      aria-pressed={selectedId === span.id} onClick={() => onSelect(span.id)}>{`열기 ${span.id}`}</button>)}
  </section>,
}));

function materialsTrace() {
  const base = syntheticSteppedAgentTrace();
  const request = syntheticContent(JSON.stringify({ question: "합성 현재 질문", history: [], available_evidence_count: 2 }));
  const actual = { question: "합성 자료 대상 질문", history: [], evidence: [
    { text: "SYNTHETIC_TARGET_EVIDENCE_FIRST" }, { text: "SYNTHETIC_TARGET_EVIDENCE_SECOND" },
  ] };
  const root = { ...base.spans[0], id: "root-independent", name: "same_recorded_name", sequence: 0, input: request };
  const model = { ...base.spans[1], id: "sibling-independent", parent_id: root.id, name: "same_recorded_name", sequence: 8, input: request };
  const delegation = { ...base.spans[2], id: "dispatch-independent", parent_id: root.id, name: "same_recorded_name", sequence: 5, input: request };
  const target = { ...base.spans[3], id: "target-independent", parent_id: delegation.id, name: "same_recorded_name", sequence: 13,
    input: syntheticContent(JSON.stringify(actual)) };
  const targetModel = { ...base.spans[4], id: "target-model-independent", parent_id: target.id, name: "same_recorded_name", sequence: 16,
    input: syntheticContent(JSON.stringify({ messages: [{ role: "user", content: JSON.stringify(actual) }] })) };
  return { ...base, run_id: "independent-material-run", root_span_id: root.id, spans: [targetModel, model, target, root, delegation] };
}

async function openMaterials(spanId = "root-independent") {
  await userEvent.click(screen.getByRole("button", { name: `열기 ${spanId}` }));
  const dialog = screen.getByRole("dialog");
  const summary = within(dialog).getByText("함께 전달된 자료", { selector: "summary" });
  if (!summary.closest("details")!.open) await userEvent.click(summary);
  return { dialog, summary, materials: within(summary.closest("details")!) };
}

it("keeps graph and modal identities distinct within the same run", async () => {
  const errors = vi.spyOn(console, "error");
  try {
    render(<AgentTracePanel trace={materialsTrace()} />);
    const current = await openMaterials();
    await userEvent.click(current.materials.getByRole("button", { name: /#14 ·/ }));
    expect(errors.mock.calls.map(args => args.join(" ")).join("\n")).not.toContain("same key");
  } finally {
    errors.mockRestore();
  }
});

it("navigates by recorded identity to real descendant material, opens it and restores focus to the selected node", async () => {
  render(<AgentTracePanel trace={materialsTrace()} />);
  const current = await openMaterials();
  expect(current.materials.getByText("사용 가능한 근거 2개")).toBeVisible();
  expect(current.dialog.textContent).not.toContain("SYNTHETIC_TARGET_EVIDENCE_FIRST");
  await userEvent.click(current.materials.getByRole("button", { name: "#14 · 에이전트 · same_recorded_name · 입력 근거 2개 보기" }));
  const selected = screen.getByRole("dialog");
  expect(within(selected).getByText("기록 #14 · 단계 상세")).toBeVisible();
  const summary = within(selected).getByText("함께 전달된 자료", { selector: "summary" });
  expect(summary.closest("details")).toHaveAttribute("open");
  expect(summary).toHaveFocus();
  expect(within(selected).getByText("SYNTHETIC_TARGET_EVIDENCE_FIRST")).toBeVisible();
  expect(within(selected).getByText("SYNTHETIC_TARGET_EVIDENCE_SECOND")).toBeVisible();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "열기 target-independent" })).toHaveFocus();
});

it.each(["sibling", "missing-parent", "cycle"] as const)("does not offer unrelated or invalid material paths: %s", async scenario => {
  const trace = materialsTrace();
  const target = trace.spans.find(span => span.id === "target-independent")!;
  if (scenario === "missing-parent") target.parent_id = "missing-independent";
  if (scenario === "cycle") target.parent_id = "target-model-independent";
  render(<AgentTracePanel trace={trace} />);
  const current = await openMaterials(scenario === "sibling" ? "sibling-independent" : "root-independent");
  expect(current.materials.queryByRole("button", { name: /#14|#17/ })).not.toBeInTheDocument();
  expect(current.dialog.textContent).not.toContain("SYNTHETIC_TARGET_EVIDENCE_");
});

it("does not read withheld candidate bodies or offer metadata-only evidence as readable material", async () => {
  const trace = materialsTrace();
  const hidden = trace.spans.find(span => span.id === "target-independent")!;
  hidden.input = { ...hidden.input, content_status: "omitted_validation_failure" };
  const readHidden = vi.fn(() => { throw new Error("SYNTHETIC_WITHHELD_BODY_READ"); });
  Object.defineProperty(hidden.input, "text", { get: readHidden });
  const metadata = trace.spans.find(span => span.id === "target-model-independent")!;
  metadata.input = syntheticContent(JSON.stringify({ question: "합성 메타데이터 질문", evidence: [{ evidence_id: "synthetic-only-reference" }] }));
  const view = render(<AgentTracePanel trace={trace} />);
  const current = await openMaterials();
  expect(current.materials.queryByRole("button", { name: /#14|#17/ })).not.toBeInTheDocument();
  expect(readHidden).not.toHaveBeenCalled();
  hidden.input = { ...syntheticContent("unused"), content_status: "complete" };
  Object.defineProperty(hidden.input, "text", { get: readHidden });
  view.rerender(<AgentTracePanel trace={{ ...trace, content_retention: "metadata_only" }} />);
  expect(readHidden).not.toHaveBeenCalled();
  expect(within(screen.getByRole("dialog")).queryByRole("button", { name: /#14|#17/ })).not.toBeInTheDocument();
});

it.each([false, true])("removes pointer-clicked help on leave even when the button was keyboard-focused first (%s)", async keyboardFirst => {
  const user = userEvent.setup();
  render(<AgentTracePanel trace={materialsTrace()} />);
  await user.click(screen.getByRole("button", { name: "열기 root-independent" }));
  const dialog = screen.getByRole("dialog");
  const summary = within(dialog).getByText("적용 지침", { selector: "summary" });
  const help = within(dialog).getByRole("button", { name: "적용 지침 도움말" });
  if (keyboardFirst) {
    await user.tab();
    await user.tab();
    expect(help).toHaveFocus();
    expect(screen.getByRole("tooltip")).toBeVisible();
  }
  // Real user-event order includes pointerdown -> focus -> pointerup -> click.
  await user.click(help);
  expect(screen.getByRole("tooltip")).toBeVisible();
  expect(summary.closest("details")).not.toHaveAttribute("open");
  await user.unhover(help);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  expect(help).toHaveFocus();
  expect(screen.getByRole("dialog")).toBe(dialog);
});

it("keeps keyboard help independent from disclosure, closes on blur and dismisses before the modal", async () => {
  const user = userEvent.setup();
  render(<AgentTracePanel trace={materialsTrace()} />);
  await user.click(screen.getByRole("button", { name: "열기 root-independent" }));
  const dialog = screen.getByRole("dialog");
  const summary = within(dialog).getByText("적용 지침", { selector: "summary" });
  const help = within(dialog).getByRole("button", { name: "적용 지침 도움말" });
  await user.tab();
  await user.tab();
  expect(screen.getByRole("tooltip")).toBeVisible();
  expect(summary.closest("details")).not.toHaveAttribute("open");
  expect(help).toHaveFocus();
  await user.tab();
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  await user.tab({ shift: true });
  expect(help).toHaveFocus();
  expect(screen.getByRole("tooltip")).toBeVisible();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  expect(screen.getByRole("dialog")).toBe(dialog);
  expect(help).toHaveFocus();
  expect(summary.closest("details")).not.toHaveAttribute("open");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("removes navigated material on access loss and does not carry the selection into another run with reused span IDs", async () => {
  const trace = materialsTrace();
  const view = render(<AgentTracePanel trace={trace} />);
  const current = await openMaterials();
  await userEvent.click(current.materials.getByRole("button", { name: /#14 ·/ }));
  expect(screen.getByText("SYNTHETIC_TARGET_EVIDENCE_FIRST")).toBeVisible();
  view.rerender(<AgentTracePanel trace={{ ...trace, content_retention: "metadata_only" }} />);
  expect(document.body.textContent).not.toContain("SYNTHETIC_TARGET_EVIDENCE_");
  expect(within(screen.getByRole("dialog")).queryByRole("button", { name: /#17 ·/ })).not.toBeInTheDocument();
  view.rerender(<AgentTracePanel trace={{ ...trace, run_id: "independent-next-run" }} />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(document.body.textContent).not.toContain("SYNTHETIC_TARGET_EVIDENCE_");
});
