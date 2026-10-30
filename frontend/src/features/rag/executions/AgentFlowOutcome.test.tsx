import { render, screen, within } from "@testing-library/react";
import { ExecutionDetailPage } from "./ExecutionDetailPage";
import { AgentTracePanel } from "./AgentTracePanel";
import { getExecutionDetail, type ExecutionDetail } from "./api";
import { syntheticAgentTrace } from "./agent-trace.test-support";

vi.mock("./api", () => ({ getExecutionDetail: vi.fn(), searchExecutions: vi.fn() }));
vi.mock("./mermaid-runtime", () => ({ renderMermaid: vi.fn(async (_id: string, source: string) => ({
  svg: `<svg>${Array.from(source.matchAll(/^n(\d+)\[/gm), ([, index]) =>
    `<g class="node" id="flowchart-n${index}-${index}" transform="translate(${100 + Number(index) * 120},100)"><rect width="80" height="40" /></g>`).join("")}${Array.from(source.matchAll(/\b(e\d+)@-->/g), ([, id]) => `<path id="${id}" />`).join("")}</svg>`,
})) }));

const originalGetBBox = Object.getOwnPropertyDescriptor(SVGElement.prototype, "getBBox");
beforeAll(() => Object.defineProperty(SVGElement.prototype, "getBBox", { configurable: true,
  value: () => ({ x: -40, y: -20, width: 80, height: 40 }) }));
afterAll(() => {
  if (originalGetBBox) Object.defineProperty(SVGElement.prototype, "getBBox", originalGetBBox);
  else Reflect.deleteProperty(SVGElement.prototype, "getBBox");
});
beforeEach(() => vi.mocked(getExecutionDetail).mockReset());

function detail(overrides: Partial<ExecutionDetail> = {}): ExecutionDetail {
  return { id: "synthetic-outcome", record_kind: "execution", kind: "evaluation", query: "합성 결과 질문",
    status: "completed", answer_status: "answered", quality_status: "failed", duration_ms: 15234,
    observation_complete: true, created_at: "2026-10-24T01:30:00Z", document_count: 0,
    domain_id: null, domain_slug: null, conversation_id: null, turn_id: null,
    generation: null, evidence: [], stages: [], agent_trace: syntheticAgentTrace(), ...overrides };
}

async function showDetail(value: ExecutionDetail) {
  vi.mocked(getExecutionDetail).mockResolvedValue(value);
  render(<ExecutionDetailPage id={value.id} />);
  await screen.findByRole("heading", { name: value.query });
  const diagram = within(screen.getByRole("region", { name: "에이전트 위임 그림" }));
  await diagram.findByRole("button", { name: "에이전트 · synthetic_manager · #1" });
  return diagram;
}

it("places one stored execution outcome inside the flow without treating completed agents as quality success or adding nested times", async () => {
  const diagram = await showDetail(detail());
  const summary = within(diagram.getByRole("region", { name: "실행 결과 요약" }));
  expect(screen.getAllByRole("region", { name: "실행 결과 요약" })).toHaveLength(1);
  expect(summary.getByText("실행 완료 · 품질 실패")).toBeVisible();
  expect(summary.getByText("처리 완료")).toBeVisible();
  expect(summary.getByText("답변 생성")).toBeVisible();
  expect(summary.getByText("실패", { exact: true })).toBeVisible();
  expect(summary.getByText("15.23초")).toBeVisible();
  expect(summary.queryByText("10.00초")).not.toBeInTheDocument();
  expect(summary.queryByText("통과", { exact: true })).not.toBeInTheDocument();
});

it.each([
  ["running", "실행 진행 중"], ["failed", "실행 실패"], ["cancelled", "실행 취소"], ["interrupted", "실행 중단"],
] as const)("preserves stored %s, unreviewed quality, missing time and incomplete observation", async (status, sentence) => {
  const diagram = await showDetail(detail({ status, quality_status: "unreviewed", answer_status: "insufficient_evidence",
    duration_ms: null, observation_complete: false }));
  const summary = within(diagram.getByRole("region", { name: "실행 결과 요약" }));
  expect(summary.getByText(`${sentence} · 품질 미검증`)).toBeVisible();
  expect(summary.getByText("미검증", { exact: true })).toBeVisible();
  expect(summary.getByText("근거 부족", { exact: true })).toBeVisible();
  expect(summary.getByText("시간 미기록")).toBeVisible();
  expect(summary.getByText(/관측 일부 누락/)).toBeVisible();
  expect(summary.queryByText("0.00초")).not.toBeInTheDocument();
  expect(summary.queryByText("통과", { exact: true })).not.toBeInTheDocument();
});

it("shows a recorded quality pass and zero duration without replacing zero with an absent value", async () => {
  const diagram = await showDetail(detail({ quality_status: "passed", duration_ms: 0 }));
  const summary = within(diagram.getByRole("region", { name: "실행 결과 요약" }));
  expect(summary.getByText("실행 완료 · 품질 통과")).toBeVisible();
  expect(summary.getByText("통과", { exact: true })).toBeVisible();
  expect(summary.getByText("0.00초")).toBeVisible();
  expect(summary.queryByText("시간 미기록")).not.toBeInTheDocument();
});

it("does not derive an overall outcome or duration from spans when the reusable panel has no execution summary", async () => {
  render(<AgentTracePanel trace={syntheticAgentTrace()} view="current" />);
  const diagram = within(screen.getByRole("region", { name: "에이전트 위임 그림" }));
  await diagram.findByRole("button", { name: "에이전트 · synthetic_manager · #1" });
  const summary = within(diagram.getByRole("region", { name: "실행 결과 요약" }));
  expect(summary.getByText("전체 실행 정보 미기록 · 품질 판단 불가")).toBeVisible();
  expect(summary.getAllByText("미기록", { exact: true })).toHaveLength(3);
  expect(summary.getByText("시간 미기록")).toBeVisible();
  expect(summary.queryByText("처리 완료")).not.toBeInTheDocument();
  expect(summary.queryByText("10.00초")).not.toBeInTheDocument();
});

it.each([null, { ...syntheticAgentTrace(), spans: [] }])("keeps the existing outcome summary when no flow can be drawn", async agent_trace => {
  const value = detail({ agent_trace });
  vi.mocked(getExecutionDetail).mockResolvedValue(value);
  render(<ExecutionDetailPage id={value.id} />);
  const summary = within(await screen.findByRole("region", { name: "실행 결과 요약" }));
  expect(screen.queryByRole("region", { name: "에이전트 위임 그림" })).not.toBeInTheDocument();
  expect(screen.getAllByRole("region", { name: "실행 결과 요약" })).toHaveLength(1);
  expect(summary.getByText("실패", { exact: true })).toBeVisible();
  expect(summary.getByText("15.23초")).toBeVisible();
});
