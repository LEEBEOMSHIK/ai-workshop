import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentTracePanel } from "./AgentTracePanel";
import { syntheticAgentTrace, syntheticContent, syntheticDeepAgentTrace } from "./agent-trace.test-support";

vi.mock("./mermaid-runtime", () => ({
  renderMermaid: vi.fn(async (_id: string, source: string) => ({
    svg: `<svg xmlns="http://www.w3.org/2000/svg">${Array.from(source.matchAll(/^n(\d+)\[/gm), ([, index]) =>
      `<g class="node" id="flowchart-n${index}-${index}" transform="translate(${100 + Number(index) * 120},100)"><rect width="80" height="40" /></g>`).join("")}${Array.from(source.matchAll(/\b(e\d+)@-->/g), ([, id]) => `<path id="${id}" />`).join("")}</svg>`,
  })),
}));

const originalGetBBox = Object.getOwnPropertyDescriptor(SVGElement.prototype, "getBBox");
beforeAll(() => {
  Object.defineProperty(SVGElement.prototype, "getBBox", { configurable: true,
    value: () => ({ x: -40, y: -20, width: 80, height: 40 }) });
});
afterAll(() => {
  if (originalGetBBox) Object.defineProperty(SVGElement.prototype, "getBBox", originalGetBBox);
  else Reflect.deleteProperty(SVGElement.prototype, "getBBox");
});

function selected() {
  return within(screen.getByRole("dialog"));
}

function diagram() {
  return within(screen.getByRole("region", { name: "에이전트 위임 그림" }));
}

async function records() {
  const summary = screen.getByText(/^전체 단계 기록 \(/, { selector: "summary" });
  if (!summary.closest("details")!.open) await userEvent.click(summary);
  return within(screen.getByRole("list", { name: "에이전트 실행과 위임 단계" }));
}

async function openRoot() {
  await userEvent.click(await diagram().findByRole("button", { name: "에이전트 · synthetic_manager · #1" }));
}

function content(title: string) {
  return within(technical().getByRole("region", { name: title }));
}

function technical() {
  return within(selected().getByText("원문·기술 기록", { selector: "summary" }).closest("details")!);
}

async function openTechnical() {
  const summary = selected().getByText("원문·기술 기록", { selector: "summary" });
  if (!summary.closest("details")!.open) await userEvent.click(summary);
}

async function openRaw(title: string) {
  await openTechnical();
  await userEvent.click(content(title).getByText("원문 펼치기", { selector: "summary" }));
}

async function closeDetail() {
  await userEvent.click(selected().getByRole("button", { name: "닫기" }));
}

it("opens related stages from keyboard-selectable SVG nodes and returns focus when the dialog closes", async () => {
  render(<AgentTracePanel trace={syntheticAgentTrace()} view="current" />);
  const user = userEvent.setup();
  const parent = await diagram().findByRole("button", { name: /에이전트.*synthetic_manager/ });
  const child = diagram().getByRole("button", { name: /위임.*synthetic_delegate/ });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(parent).toHaveAttribute("aria-pressed", "false");
  expect(child).toHaveAttribute("aria-haspopup", "dialog");
  parent.focus();
  expect(parent).toHaveFocus();
  await user.tab();
  expect(child).toHaveFocus();
  await user.keyboard(" ");
  expect(child).toHaveAttribute("aria-pressed", "true");
  expect(parent).toHaveAttribute("aria-pressed", "false");
  expect(screen.getByRole("dialog", { name: "위임 · synthetic_delegate" })).toHaveAttribute("aria-modal", "true");
  expect(selected().getByRole("button", { name: "닫기" })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(child).toHaveFocus();
  await user.tab();
  await user.keyboard("{Enter}");
  expect(selected().getByRole("heading", { name: "에이전트 · synthetic_writer" })).toBeVisible();
  await openTechnical();
  await user.click(technical().getByText("단계 기록 정보", { selector: "summary" }));
  expect(technical().getByText("#2 synthetic_delegate")).toBeVisible();
});

it("resets selection when the run changes even if span identifiers are reused", async () => {
  const trace = syntheticAgentTrace();
  const view = render(<AgentTracePanel trace={trace} view="current" />);
  await userEvent.click((await records()).getByRole("button", { name: /모델 호출.*synthetic_generation/ }));
  await openRaw("전달 입력");
  expect(content("전달 입력").getByText(/합성 실제 요청/, { selector: "pre" })).toBeVisible();
  view.rerender(<AgentTracePanel trace={{ ...trace, run_id: "different-synthetic-run" }} view="current" />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByText(/합성 실제 요청/)).not.toBeInTheDocument();
  expect((await records()).getByRole("button", { name: /모델 호출.*synthetic_generation/ })).toHaveAttribute("aria-pressed", "false");
  await openRoot();
  expect(screen.getByRole("dialog", { name: "에이전트 · synthetic_manager" })).toBeVisible();
});

it("shows tool arguments and returned content without treating a tool as an agent", async () => {
  render(<AgentTracePanel trace={syntheticAgentTrace()} view="current" />);
  await userEvent.click((await records()).getByRole("button", { name: /도구.*synthetic_evidence/ }));
  await openTechnical();
  expect(technical().getByText("도구 호출 인자")).toBeVisible();
  await openRaw("전달 입력");
  await openRaw("반환 결과");
  expect(selected().getByText('{"question":"합성 도구 질문"}')).toBeVisible();
  expect(selected().getByText('{"evidence":"합성 도구 결과"}')).toBeVisible();
  expect(selected().queryByText("위임받은 에이전트")).not.toBeInTheDocument();
});

it("distinguishes control handoff from a delegated tool result", async () => {
  const trace = syntheticAgentTrace();
  trace.spans[1] = { ...trace.spans[1], delegation_mode: "handoff" };
  render(<AgentTracePanel trace={trace} />);
  await userEvent.click(await diagram().findByRole("button", { name: /위임.*synthetic_delegate/ }));
  await openTechnical();
  expect(technical().getByText("제어권 인계 (handoff)")).toBeVisible();
  expect(technical().queryByText(/결과를 돌려받는 도구 위임/)).not.toBeInTheDocument();
});

it("leaves missing model tokens and duration unknown instead of replacing them with zero", async () => {
  const trace = syntheticAgentTrace();
  trace.spans[4] = { ...trace.spans[4], state: "running", duration_ms: null, ended_at: null,
    input_tokens: null, output_tokens: null };
  render(<AgentTracePanel trace={trace} />);
  await userEvent.click((await records()).getByRole("button", { name: /모델 호출.*synthetic_generation/ }));
  await openTechnical();
  expect(technical().getAllByText("미보고")).toHaveLength(2);
  expect(selected().getByText(/시간 미기록/)).toBeVisible();
  await userEvent.click(selected().getByText("단계 기록 정보", { selector: "summary" }));
  expect(selected().getByText("종료 시각 미기록")).toBeVisible();
  expect(selected().queryByText("0 토큰")).not.toBeInTheDocument();
  expect(selected().queryByText(/0\.00초/)).not.toBeInTheDocument();
});

it("keeps a child cancellation warning visible without presenting it as model termination", async () => {
  const trace = syntheticAgentTrace();
  trace.spans[4] = { ...trace.spans[4], state: "cancelled" };
  render(<AgentTracePanel trace={trace} />);
  expect(screen.getByText(/단계 취소 기록.*실제 모델 실행 종료 여부.*별도 확인/)).toBeVisible();
  await userEvent.click((await records()).getByRole("button", { name: /모델 호출.*synthetic_generation/ }));
  expect(selected().getByText(/단계 취소 기록.*실제 모델 실행 종료 여부.*별도 확인/)).toBeVisible();
  expect(selected().queryByText("모델 종료 확인됨")).not.toBeInTheDocument();
});

it.each([undefined, "metadata_only"] as const)("does not expose legacy complete bodies with retention %s", async contentRetention => {
  const trace = syntheticAgentTrace();
  if (contentRetention) trace.content_retention = contentRetention;
  // Old wire records predate this required field in the generated response schema.
  else Reflect.deleteProperty(trace, "content_retention");
  render(<AgentTracePanel trace={trace} view="history" />);
  await openRoot();
  expect(screen.queryByText("합성 위임 작업")).not.toBeInTheDocument();
  expect(screen.queryByText("합성 역할 지침")).not.toBeInTheDocument();
  await openTechnical();
  expect(content("전달 입력").getByText(/본문 미보관/)).toBeVisible();
  expect(content("전달 입력").getByText(/당시.*보관하지 않아/)).toBeVisible();
  expect(content("전달 입력").queryByText("원문 펼치기")).not.toBeInTheDocument();
  expect(screen.queryByText("합성 위임 작업")).not.toBeInTheDocument();
  expect(screen.queryByText("합성 역할 지침")).not.toBeInTheDocument();
});

it("shows retained historical instructions, input and observed output as plain text", async () => {
  const trace = syntheticAgentTrace();
  trace.spans[0] = { ...trace.spans[0],
    input: syntheticContent('합성 저장 입력 <script>unsafe()</script> https://example.invalid'),
    output: syntheticContent("합성 검증 전 반환값") };
  render(<AgentTracePanel trace={trace} view="history" />);
  expect(screen.getByText(/본문 보관이 적용된 실행 기록.*각 항목의 상태/)).toBeVisible();
  await openRoot();
  for (const title of ["전달 지침", "전달 입력", "반환 결과"]) {
    await openRaw(title);
  }
  expect(selected().getByText("합성 역할 지침", { selector: "pre" })).toBeVisible();
  expect(selected().getByText('합성 저장 입력 <script>unsafe()</script> https://example.invalid', { selector: "pre" })).toBeVisible();
  const output = selected().getByRole("region", { name: "반환 결과" });
  expect(within(output).getByText("합성 검증 전 반환값", { selector: "pre" })).toBeVisible();
  expect(within(output).getByText(/단계에서 관측한 반환값.*검증된 최종 답변과 구분/)).toBeVisible();
  expect(screen.getAllByText(/단계에서 관측한 반환값.*검증된 최종 답변과 구분/)).toHaveLength(2);
  expect(screen.getByRole("dialog").querySelector("script, a")).toBeNull();
});

it("keeps current complete content visible without treating metadata retention as a display denial", async () => {
  render(<AgentTracePanel trace={{ ...syntheticAgentTrace(), content_retention: "metadata_only" }} view="current" />);
  await openRoot();
  await openRaw("전달 입력");
  expect(selected().getByText("합성 위임 작업", { selector: "pre" })).toBeVisible();
  expect(screen.getByText(/현재 응답의 단계 기록/)).toBeVisible();
  expect(screen.queryByText(/다시 열면 보관되지 않습니다/)).not.toBeInTheDocument();
});

it.each(["current", "history"] as const)("distinguishes omitted, uncaptured and empty content in the %s view", async view => {
  const trace = syntheticAgentTrace();
  trace.spans[0] = { ...trace.spans[0],
    input: { content_status: "omitted_size_limit", text: null, characters: 40000 },
    instructions: { content_status: "disabled", text: null, characters: null },
    output: syntheticContent("") };
  render(<AgentTracePanel trace={trace} view={view} />);
  await openRoot();
  await openTechnical();
  expect(content("전달 입력").getByText("크기 제한으로 본문 생략")).toBeVisible();
  await userEvent.click(content("전달 입력").getByText("기록 정보", { selector: "summary" }));
  expect(content("전달 입력").getByText("40,000")).toBeVisible();
  expect(content("전달 입력").getByText(/실제 입력이나 결과가 잘렸다는 뜻은 아닙니다/)).toBeVisible();
  expect(content("전달 지침").getByText(/본문 수집 안 함/)).toBeVisible();
  await userEvent.click(content("전달 지침").getByText("기록 정보", { selector: "summary" }));
  expect(content("전달 지침").getByText("문자 수").nextElementSibling).toHaveTextContent("미기록");
  expect(content("전달 지침").getByText(/당시.*본문을 수집하지 않았습니다/)).toBeVisible();
  expect(content("반환 결과").getByText("빈 문자열로 기록되었습니다.")).toBeVisible();
});

it("distinguishes an inapplicable field from uncaptured instructions and an unretained input", async () => {
  const trace = syntheticAgentTrace();
  trace.spans[0] = { ...trace.spans[0],
    instructions: { content_status: "disabled", text: null, characters: null },
    input: { content_status: "not_retained", text: null, characters: 12 },
    output: { content_status: "not_applicable", text: null, characters: null } };
  render(<AgentTracePanel trace={trace} />);
  await openRoot();
  await openTechnical();
  expect(content("전달 지침").getByText(/당시.*본문을 수집하지 않았습니다/)).toBeVisible();
  expect(content("전달 입력").getByText(/당시.*보관하지 않아/)).toBeVisible();
  expect(content("반환 결과").getByText(/이 단계에는 이 항목이 해당하지 않습니다/)).toBeVisible();
  expect(selected().queryByText("빈 문자열로 기록되었습니다.")).not.toBeInTheDocument();
});

it.each(["not_retained", "disabled", "not_applicable", "omitted_size_limit", "omitted_validation_failure"] as const)(
  "withholds stray body text when a retained record reports %s", async contentStatus => {
    const trace = syntheticAgentTrace();
    trace.spans[0] = { ...trace.spans[0], output: {
      content_status: contentStatus, text: "합성 비표시 반환 본문", characters: 13,
    } };
    render(<AgentTracePanel trace={trace} />);
    await openRoot();
    expect(selected().queryByText("합성 비표시 반환 본문")).not.toBeInTheDocument();
    await openTechnical();
    expect(selected().queryByText("합성 비표시 반환 본문")).not.toBeInTheDocument();
    expect(technical().getByRole("region", { name: "반환 결과" }).querySelector("pre")).toBeNull();
    expect(content("반환 결과").queryByText("원문 펼치기")).not.toBeInTheDocument();
  },
);

it("preserves failure and partial observation information", async () => {
  const trace = syntheticAgentTrace();
  trace.observation_complete = false;
  trace.truncated = true;
  trace.spans[0] = { ...trace.spans[0], state: "failed", error_code: "agent_model_call_limit" };
  render(<AgentTracePanel trace={trace} />);
  expect(screen.getByText(/일부 관측 기록이 누락/)).toBeVisible();
  expect(screen.getByText(/일부 단계 또는 본문이 생략/)).toBeVisible();
  await openRoot();
  expect(selected().getByRole("alert")).toHaveTextContent("agent_model_call_limit");
  expect(selected().getByText(/최종 답변의 품질 통과를 뜻하지 않습니다/)).toBeVisible();
  expect(screen.queryByText(/^품질.*통과$/)).not.toBeInTheDocument();
});

it("builds existing source links only from structured evidence references", async () => {
  const trace = syntheticAgentTrace();
  trace.spans[0] = { ...trace.spans[0], evidence_refs: [
    { document_id: "synthetic-doc", asset_version_id: "synthetic-asset", projection_id: "synthetic-projection" },
  ] };
  render(<AgentTracePanel trace={trace} />);
  await openRoot();
  await openTechnical();
  await userEvent.click(technical().getByText("연결된 원문 (1)", { selector: "summary" }));
  expect(technical().getByRole("link", { name: "원문 1 열기" })).toHaveAttribute("href", "/workshop/rag/sources/synthetic-asset?projectionId=synthetic-projection");
  expect(selected().getAllByRole("link")).toHaveLength(1);
});

it("distinguishes withheld invalid output from uncaptured and size-limited content", async () => {
  const trace = syntheticAgentTrace();
  trace.spans[0] = { ...trace.spans[0], output: {
    content_status: "omitted_validation_failure", text: null, characters: 17, sha256: "b".repeat(64),
  } };
  render(<AgentTracePanel trace={trace} view="current" />);
  await openRoot();
  await openTechnical();
  const output = content("반환 결과");
  expect(output.getByText("답변 검증 실패로 본문 숨김")).toBeVisible();
  expect(output.getByText(/인용 또는 답변 검증을 통과하지 못한 결과/)).toBeVisible();
  await userEvent.click(output.getByText("기록 정보", { selector: "summary" }));
  expect(output.getByText("17")).toBeVisible();
  expect(output.getByText("b".repeat(64))).toBeVisible();
  expect(output.queryByText(/크기 제한/)).not.toBeInTheDocument();
  expect(selected().getByRole("region", { name: "반환 결과" }).querySelector("pre")).toBeNull();
});

it("does not invent stages for a trace with no recorded spans", () => {
  const trace = { ...syntheticAgentTrace(), root_span_id: null, spans: [] };
  render(<AgentTracePanel trace={trace} />);
  expect(screen.getByText(/저장된 단계가 없습니다/)).toBeVisible();
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});

it("summarizes recorded span kinds instead of treating every stage as an agent or a completed call", async () => {
  const trace = syntheticAgentTrace();
  trace.spans[4] = { ...trace.spans[4], state: "failed" };
  trace.observation_complete = false;
  render(<AgentTracePanel trace={trace} />);
  await diagram().findByRole("button", { name: /에이전트.*synthetic_manager/ });
  const summary = within(screen.getByLabelText("기록된 단계 요약"));
  expect(summary.getByText("에이전트").parentElement).toHaveTextContent("2 단계");
  expect(summary.getByText("위임").parentElement).toHaveTextContent("1 단계");
  expect(summary.getByText("모델 호출").parentElement).toHaveTextContent("1 단계");
  expect(summary.getByText("도구").parentElement).toHaveTextContent("1 단계");
  expect(screen.getByText(/일부 관측 기록이 누락/)).toBeVisible();
});

it("keeps execution identifiers and precise times collapsed until record details are opened", async () => {
  const trace = syntheticAgentTrace();
  render(<AgentTracePanel trace={trace} />);
  const record = screen.getByText("실행 기록 정보", { selector: "summary" }).closest("details")!;
  expect(record).not.toHaveAttribute("open");
  expect(within(record).getByText(trace.run_id)).not.toBeVisible();
  const user = userEvent.setup();
  const disclosure = within(record).getByText("실행 기록 정보", { selector: "summary" });
  disclosure.focus();
  expect(disclosure).toHaveFocus();
  // jsdom does not implement the browser's native Enter-to-toggle summary action.
  await user.click(disclosure);
  expect(within(record).getByText(trace.run_id)).toBeVisible();
  expect(within(record).getByText("10")).toBeVisible();
  expect(within(record).getByText(/관측 갱신/)).toBeVisible();
  await openRoot();
  expect(selected().getByText("원문·기술 기록", { selector: "summary" }).closest("details")!).not.toHaveAttribute("open");
  await openTechnical();
  const stage = technical().getByText("단계 기록 정보", { selector: "summary" }).closest("details")!;
  expect(stage).not.toHaveAttribute("open");
  expect(within(stage).getByText("manager")).not.toBeVisible();
  await user.click(within(stage).getByText("단계 기록 정보", { selector: "summary" }));
  expect(within(stage).getByText("manager")).toBeVisible();
  expect(within(stage).getByText("시작")).toBeVisible();
});

it("highlights the delegation direction and keeps model-only metadata off other stage kinds", async () => {
  render(<AgentTracePanel trace={syntheticAgentTrace()} />);
  await openRoot();
  await openTechnical();
  expect(selected().queryByText("공급자 보고 입력")).not.toBeInTheDocument();
  await closeDetail();
  await userEvent.click(diagram().getByRole("button", { name: /위임.*synthetic_delegate/ }));
  await openTechnical();
  const source = technical().getByText("synthetic_manager", { selector: "strong" });
  expect(source.parentElement).toHaveTextContent("synthetic_manager → synthetic_writer");
  expect(technical().getByText("synthetic_writer", { selector: "strong" })).toBeVisible();
  expect(selected().queryByText("모델")).not.toBeInTheDocument();
  expect(selected().queryByText("공급자 보고 출력")).not.toBeInTheDocument();
  await closeDetail();
  await userEvent.click((await records()).getByRole("button", { name: /모델 호출.*synthetic_generation/ }));
  await openTechnical();
  expect(technical().getByText("synthetic-model")).toBeVisible();
  expect(technical().getByText("0 토큰")).toBeVisible();
  expect(technical().getByText("12 토큰")).toBeVisible();
});

it("connects siblings to their recorded parent even when records arrive out of sequence", async () => {
  const trace = syntheticAgentTrace();
  const [manager, delegate, writer, tool, model] = trace.spans;
  trace.spans = [model, delegate, tool, manager, writer];
  render(<AgentTracePanel trace={trace} />);
  await records();
  const children = within(screen.getByRole("list", { name: "synthetic_writer의 하위 단계" }));
  const toolButton = children.getByRole("button", { name: /도구.*synthetic_evidence/ });
  const modelButton = children.getByRole("button", { name: /모델 호출.*synthetic_generation/ });
  expect(within(toolButton.closest("li")!).queryByRole("button", { name: /synthetic_generation/ })).not.toBeInTheDocument();
  expect(modelButton.closest("ol")).toBe(toolButton.closest("ol"));
  const root = screen.getByRole("list", { name: "에이전트 실행과 위임 단계" });
  expect(within(root).getAllByRole("button")[0]).toHaveAccessibleName(/에이전트.*synthetic_manager/);
  expect(within(root).getAllByRole("button")).toHaveLength(5);
});

it("marks a missing parent without inventing a top-level relationship", async () => {
  const trace = syntheticAgentTrace();
  trace.spans[2] = { ...trace.spans[2], parent_id: "not-recorded" };
  render(<AgentTracePanel trace={trace} />);
  expect(screen.getByText(/부모 관계를 연결할 수 없는 단계/)).toBeVisible();
  await userEvent.click(await diagram().findByRole("button", { name: /에이전트.*synthetic_writer/ }));
  await openTechnical();
  expect(technical().getByText("상위 관계 미기록", { selector: "p" })).toBeVisible();
  await userEvent.click(technical().getByText("단계 기록 정보", { selector: "summary" }));
  expect(technical().getByText("상위 단계 미기록")).toBeVisible();
  expect(selected().queryByText("최상위 실행")).not.toBeInTheDocument();
});

it("renders cyclic parent records once without creating a false connected tree", async () => {
  const trace = syntheticAgentTrace();
  trace.spans = [
    { ...trace.spans[0], parent_id: "delegate" },
    trace.spans[1],
  ];
  render(<AgentTracePanel trace={trace} />);
  expect(screen.getByText(/부모 관계를 연결할 수 없는 단계/)).toBeVisible();
  expect((await records()).getAllByRole("button")).toHaveLength(2);
  expect(screen.queryByRole("list", { name: /의 하위 단계/ })).not.toBeInTheDocument();
});

it("compares only observed durations and leaves unknown time without a zero-valued meter", async () => {
  const trace = syntheticAgentTrace();
  trace.spans[0] = { ...trace.spans[0], duration_ms: 9000 };
  trace.spans[1] = { ...trace.spans[1], duration_ms: 1000 };
  trace.spans[2] = { ...trace.spans[2], duration_ms: null };
  trace.spans[3] = { ...trace.spans[3], duration_ms: 0 };
  render(<AgentTracePanel trace={trace} />);
  await records();
  const shorter = screen.getByRole("meter", { name: "synthetic_delegate 관측 소요 시간" });
  expect(shorter).toHaveAttribute("aria-valuenow", "1000");
  expect(shorter).toHaveAttribute("aria-valuemax", "9000");
  expect(screen.getByRole("meter", { name: "synthetic_evidence 관측 소요 시간" })).toHaveAttribute("aria-valuenow", "0");
  expect(screen.queryByRole("meter", { name: "synthetic_writer 관측 소요 시간" })).not.toBeInTheDocument();
  expect(screen.getByText(/중첩.*합산하지/)).toBeVisible();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
});

it("keeps every stage selectable at the maximum recorded nesting depth", async () => {
  render(<AgentTracePanel trace={syntheticDeepAgentTrace()} />);
  const buttons = await diagram().findAllByRole("button", { name: /^에이전트 · synthetic_nested_/ });
  expect(buttons).toHaveLength(64);
  await userEvent.click(buttons[63]);
  expect(selected().getByRole("heading", { name: "에이전트 · synthetic_nested_64" })).toBeVisible();
  expect(buttons[63]).toHaveAttribute("aria-pressed", "true");
});
