import { render, screen, within } from "@testing-library/react";
import { beforeAll, afterAll, beforeEach, expect, it, vi } from "vitest";
import { AgentTracePanel } from "./AgentTracePanel";
import { ExecutionDetailPage } from "./ExecutionDetailPage";
import { getExecutionDetail, type ExecutionDetail } from "./api";
import { syntheticSteppedAgentTrace } from "./agent-trace.test-support";

vi.mock("./api", () => ({ getExecutionDetail: vi.fn(), searchExecutions: vi.fn() }));
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
beforeEach(() => { vi.mocked(getExecutionDetail).mockReset(); });

function detail(overrides: Partial<ExecutionDetail> = {}): ExecutionDetail {
  const trace = syntheticSteppedAgentTrace();
  trace.spans = trace.spans.map((span, index) => ({ ...span, duration_ms: index ? 999000 : 432100 }));
  return { id: "independent-flow-outcome", record_kind: "execution", kind: "conversation", query: "합성 전체 결과 질문",
    status: "completed", answer_status: "answered", duration_ms: 125321, quality_status: "failed",
    created_at: "2026-10-24T01:00:00Z", document_count: 0, domain_id: null, domain_slug: null,
    conversation_id: null, turn_id: null, observation_complete: true, generation: null,
    evidence: [], stages: [], agent_trace: trace, ...overrides };
}

async function readFlowOutcome(value: ExecutionDetail) {
  vi.mocked(getExecutionDetail).mockResolvedValue(value);
  render(<ExecutionDetailPage id={value.id} />);
  const panel = await screen.findByRole("region", { name: "에이전트 위임 흐름" });
  const diagram = within(panel).getByRole("region", { name: "에이전트 위임 그림" });
  await within(diagram).findByRole("button", { name: "에이전트 · synthetic_manager · #1" });
  const outcome = within(diagram).getByRole("region", { name: "실행 결과 요약" });
  expect(screen.getAllByRole("region", { name: "실행 결과 요약" })).toHaveLength(1);
  return within(outcome);
}

it("passes authoritative execution fields through the real detail, panel and diagram without promoting completion to quality success", async () => {
  const outcome = await readFlowOutcome(detail());
  expect(outcome.getByText("실행", { exact: true }).parentElement).toHaveTextContent("완료");
  expect(outcome.getByText("답변", { exact: true }).parentElement).toHaveTextContent("답변 생성");
  expect(outcome.getByText("품질", { exact: true }).parentElement).toHaveTextContent("실패");
  expect(outcome.getByText("전체 소요 시간", { exact: true }).parentElement).toHaveTextContent("125.32초");
  expect(outcome.queryByText(/품질 통과|검증 성공/)).not.toBeInTheDocument();
  expect(outcome.queryByText("432.10초")).not.toBeInTheDocument();
  expect(outcome.queryByText("999.00초")).not.toBeInTheDocument();
});

it.each([null, 0])("keeps unreviewed quality and authoritative duration %s separate from completed nested spans", async durationMs => {
  const outcome = await readFlowOutcome(detail({ quality_status: "unreviewed", duration_ms: durationMs }));
  expect(outcome.getByText("품질", { exact: true }).parentElement).toHaveTextContent("미검증");
  expect(outcome.getByText("전체 소요 시간", { exact: true }).parentElement)
    .toHaveTextContent(durationMs === null ? "시간 미기록" : "0.00초");
  expect(outcome.queryByText(/품질 통과/)).not.toBeInTheDocument();
});

it("does not infer an overall result or time when a reused trace panel lacks execution metadata", async () => {
  render(<AgentTracePanel trace={syntheticSteppedAgentTrace()} view="current" />);
  const diagram = within(screen.getByRole("region", { name: "에이전트 위임 그림" }));
  await diagram.findByRole("button", { name: "에이전트 · synthetic_manager · #1" });
  const region = diagram.getByRole("region", { name: "실행 결과 요약" });
  expect(region).toHaveTextContent("전체 실행 정보 미기록");
  expect(region).toHaveTextContent(/품질 판단 불가|품질 미기록|미검증/);
  expect(within(region).getByText("전체 소요 시간", { exact: true }).parentElement).toHaveTextContent("시간 미기록");
  expect(region).not.toHaveTextContent(/실행 완료|품질 통과|답변 생성/);
});

it("retains the existing single summary for a stored execution that has no agent trace", async () => {
  const value = detail({ agent_trace: null, duration_ms: 0, quality_status: "unreviewed" });
  vi.mocked(getExecutionDetail).mockResolvedValue(value);
  render(<ExecutionDetailPage id={value.id} />);
  const outcome = await screen.findByRole("region", { name: "실행 결과 요약" });
  expect(screen.getAllByRole("region", { name: "실행 결과 요약" })).toHaveLength(1);
  expect(outcome).toHaveTextContent("0.00초");
  expect(outcome).toHaveTextContent("미검증");
  expect(screen.queryByRole("region", { name: "에이전트 위임 그림" })).not.toBeInTheDocument();
});
