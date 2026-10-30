import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentTracePanel } from "./AgentTracePanel";
import { syntheticSteppedAgentTrace } from "./agent-trace.test-support";
import { buildAgentFlow } from "./agent-flow";
import { buildMermaidGraph } from "./mermaid-agent-graph";

vi.mock("./mermaid-runtime", () => ({
  renderMermaid: vi.fn(async () => ({ svg: "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>" })),
}));

async function records() {
  await userEvent.click(screen.getByText(/^전체 단계 기록 \(/, { selector: "summary" }));
  return within(screen.getByRole("list", { name: "에이전트 실행과 위임 단계" }));
}

it("renders a direct root specialist and its model without inventing manager or delegation records", async () => {
  const trace = syntheticSteppedAgentTrace();
  const specialist = { ...trace.spans[3], parent_id: null, sequence: 0 };
  const model = { ...trace.spans[4], sequence: 1 };
  const graph = buildMermaidGraph(buildAgentFlow([specialist, model]));
  expect(graph.nodes.map(node => node.spanId)).toEqual(["writer", "model"]);
  expect(graph.edges.map(edge => [edge.sourceId, edge.targetId])).toEqual([["writer", "model"]]);
  render(<AgentTracePanel trace={{ ...trace, root_span_id: specialist.id, spans: [specialist, model] }} />);
  const list = await records();
  expect(list.getAllByRole("button")).toHaveLength(2);
  expect(list.getByRole("button", { name: /에이전트.*synthetic_writer/ })).toBeVisible();
  expect(list.queryByRole("button", { name: /synthetic_manager|synthetic_delegate|synthetic_coordination/ })).not.toBeInTheDocument();
  await userEvent.click(list.getByRole("button", { name: /모델 호출.*synthetic_generation/ }));
  expect(screen.getByRole("dialog", { name: /모델 호출.*synthetic_generation/ })).toBeVisible();
});

it("preserves all five recorded stages in the existing manager delegation path", async () => {
  render(<AgentTracePanel trace={syntheticSteppedAgentTrace()} />);
  const list = await records();
  expect(list.getAllByRole("button")).toHaveLength(5);
  expect(list.getByRole("button", { name: /에이전트.*synthetic_manager/ })).toBeVisible();
  expect(list.getByRole("button", { name: /위임.*synthetic_delegate/ })).toBeVisible();
  expect(list.getByRole("button", { name: /모델 호출.*synthetic_coordination/ })).toBeVisible();
});
