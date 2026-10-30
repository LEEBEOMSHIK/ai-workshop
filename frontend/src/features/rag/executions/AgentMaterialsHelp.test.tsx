import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentSpanModal } from "./AgentSpanModal";
import { buildAgentFlow, type AgentSpan } from "./agent-flow";
import { syntheticContent, syntheticSteppedAgentTrace } from "./agent-trace.test-support";

function materialSpans() {
  const spans = syntheticSteppedAgentTrace().spans;
  return spans.map(span => ({ ...span, input: syntheticContent(JSON.stringify(span.id === "writer"
    ? { question: "합성 자료 질문", evidence: [{ text: "합성 첫 근거" }, { text: "합성 둘째 근거" }] }
    : span.id === "model" ? { messages: [{ role: "user", content: JSON.stringify({ question: "합성 자료 질문", evidence: [{ text: "합성 모델 근거" }] }) }] }
      : { question: "합성 자료 질문", history: [], available_evidence_count: 7 })) }));
}

function Harness({ spans = materialSpans(), allowed = true, startId = "manager" }: {
  spans?: AgentSpan[]; allowed?: boolean; startId?: string;
}) {
  const [selection, setSelection] = useState<{ id: string; materials?: boolean } | null>(null);
  const flow = buildAgentFlow(spans);
  const span = selection ? flow.byId.get(selection.id) : undefined;
  return <>
    <section aria-label="에이전트 위임 그림" tabIndex={-1}>
      {spans.map(item => <button key={item.id} data-agent-span-id={item.id}
        onClick={() => setSelection({ id: item.id })}>{item.id === startId ? "시작 단계 열기" : `${item.id} 단계 열기`}</button>)}
    </section>
    {span ? <AgentSpanModal span={span} flow={flow} parent={span.parent_id ? flow.byId.get(span.parent_id) : undefined}
      showCompleteBody={allowed} onClose={() => setSelection(null)} initialSection={selection?.materials ? "materials" : undefined}
      onSelectMaterials={id => setSelection({ id, materials: true })} /> : null}
  </>;
}

async function openMaterials() {
  await userEvent.click(screen.getByRole("button", { name: "시작 단계 열기" }));
  await userEvent.click(screen.getByText("함께 전달된 자료", { selector: "summary" }));
}

it("moves from a count-only input to the actual descendant input, opens its materials, and restores the selected node", async () => {
  render(<Harness />);
  await openMaterials();
  expect(screen.getByText("사용 가능한 근거 7개")).toBeVisible();
  expect(screen.queryByText("합성 첫 근거")).not.toBeInTheDocument();
  expect(screen.queryByText("입력에 기록된 근거 7개")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /#4.*synthetic_writer.*근거 2개/ }));
  expect(screen.getByRole("dialog", { name: "에이전트 · synthetic_writer" })).toBeVisible();
  expect(screen.getByText("함께 전달된 자료", { selector: "summary" })).toHaveFocus();
  expect(screen.getByText("합성 첫 근거")).toBeVisible();
  expect(screen.getByText("합성 둘째 근거")).toBeVisible();
  expect(screen.getByText("입력에 기록된 근거 2개")).toBeVisible();
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "writer 단계 열기" })).toHaveFocus();
});

it("does not cross a sibling branch or use the common authority references as input materials", async () => {
  const spans = materialSpans().map(span => span.id === "manager-model" ? { ...span,
    evidence_refs: [{ document_id: "synthetic-doc", asset_version_id: "synthetic-version", projection_id: "synthetic-projection" }] } : span);
  render(<Harness spans={spans} startId="manager-model" />);
  await openMaterials();
  expect(screen.queryByRole("button", { name: /synthetic_writer.*근거/ })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /synthetic_generation.*근거/ })).not.toBeInTheDocument();
  expect(screen.getByText(/연결된 상위·하위 단계.*확인 가능한 근거 본문.*없/)).toBeVisible();
});

it("requires readable evidence text and excludes disconnected, cyclic and same-name records", async () => {
  const original = materialSpans();
  const spans: AgentSpan[] = original.map(span => span.id === "writer" ? { ...span,
    input: syntheticContent('{"evidence":[{"unsupported":"NOT_A_BODY"},{"text":" "}]}') }
    : span.id === "model" ? { ...span, input: syntheticContent('{"available_evidence_count":55}') } : span);
  spans.push({ ...original[3], id: "same-name-unconnected", parent_id: null, sequence: 9 });
  spans.push({ ...original[3], id: "orphan", parent_id: "missing-parent", sequence: 10 });
  spans.push({ ...original[3], id: "cycle", parent_id: "cycle", sequence: 11 });
  render(<Harness spans={spans} />);
  await openMaterials();
  expect(screen.queryByRole("button", { name: /#\d+.*근거 \d+개/ })).not.toBeInTheDocument();
  expect(screen.queryByText("NOT_A_BODY")).not.toBeInTheDocument();
  expect(screen.getByText(/연결된 상위·하위 단계.*확인 가능한 근거 본문.*없/)).toBeVisible();
});

it("does not read hidden related bodies and removes visible materials and navigation when access is withdrawn", async () => {
  const spans = materialSpans();
  const view = render(<Harness spans={spans} />);
  await openMaterials();
  await userEvent.click(screen.getByRole("button", { name: /#4.*근거 2개/ }));
  expect(screen.getByText("합성 첫 근거")).toBeVisible();
  const denied = spans.map(span => {
    const input = { ...span.input! };
    Object.defineProperty(input, "text", { get: () => { throw new Error("DENIED_BODY_READ"); } });
    return { ...span, input };
  });
  view.rerender(<Harness spans={denied} allowed={false} />);
  expect(document.body.textContent).not.toContain("합성 첫 근거");
  expect(screen.queryByRole("button", { name: /#\d+.*근거 \d+개/ })).not.toBeInTheDocument();
  expect(screen.getAllByText("당시 본문 미보관").length).toBeGreaterThan(0);
});

it("keeps an explicit empty evidence array distinct from a candidate count", async () => {
  const spans = materialSpans().map(span => ({ ...span, input: syntheticContent('{"history":[],"evidence":[],"available_evidence_count":0}') }));
  render(<Harness spans={spans} />);
  await openMaterials();
  expect(screen.getByText("사용 가능한 근거 0개")).toBeVisible();
  expect(screen.getByText("입력에 기록된 근거 0개")).toBeVisible();
  expect(screen.getByText("입력 근거 배열이 비어 있습니다.")).toBeVisible();
  expect(screen.queryByRole("button", { name: /#\d+.*근거 \d+개/ })).not.toBeInTheDocument();
});

it("opens the three help explanations independently of body disclosures and gives Escape priority over the modal", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "시작 단계 열기" }));
  for (const title of ["적용 지침", "함께 전달된 자료", "원문·기술 기록"]) {
    const help = screen.getByRole("button", { name: `${title} 도움말` });
    await user.click(help);
    expect(screen.getByRole("tooltip")).toBeVisible();
    expect(help).toHaveAttribute("aria-describedby", screen.getByRole("tooltip").id);
    expect(screen.getByText(title, { selector: "summary" }).closest("details")).not.toHaveAttribute("open");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    expect(screen.getByRole("dialog")).toBeVisible();
    expect(help).toHaveFocus();
  }
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("keeps hover help readable while crossing into its explanation and closes it after leaving", async () => {
  render(<Harness />);
  await userEvent.click(screen.getByRole("button", { name: "시작 단계 열기" }));
  const help = screen.getByRole("button", { name: "함께 전달된 자료 도움말" });
  fireEvent.mouseEnter(help);
  const explanation = screen.getByRole("tooltip");
  expect(explanation).toHaveTextContent(/대화 이력.*검색 근거/);
  fireEvent.mouseLeave(help, { relatedTarget: explanation });
  fireEvent.mouseEnter(explanation, { relatedTarget: help });
  expect(screen.getByRole("tooltip")).toBeVisible();
  fireEvent.mouseLeave(explanation, { relatedTarget: screen.getByRole("button", { name: "닫기" }) });
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  expect(within(screen.getByRole("dialog")).getByText("함께 전달된 자료", { selector: "summary" }).closest("details")).not.toHaveAttribute("open");
});

it("does not keep help pinned by a mouse click or the focus caused by that click", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "시작 단계 열기" }));
  const help = screen.getByRole("button", { name: "함께 전달된 자료 도움말" });
  await user.click(help);
  expect(screen.getByRole("tooltip")).toBeVisible();
  expect(help).toHaveFocus();
  await user.unhover(help);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  expect(help).toHaveFocus();
  expect(screen.getByText("함께 전달된 자료", { selector: "summary" }).closest("details")).not.toHaveAttribute("open");
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("keeps keyboard-focus help after pointer leave and dismisses it before the modal", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "시작 단계 열기" }));
  await user.tab();
  await user.tab();
  const help = screen.getByRole("button", { name: "적용 지침 도움말" });
  expect(help).toHaveFocus();
  expect(screen.getByRole("tooltip")).toBeVisible();
  await user.hover(help);
  await user.unhover(help);
  expect(screen.getByRole("tooltip")).toBeVisible();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  expect(help).toHaveFocus();
  expect(screen.getByRole("dialog")).toBeVisible();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
