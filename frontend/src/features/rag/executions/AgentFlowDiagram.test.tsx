import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentFlowDiagram } from "./AgentFlowDiagram";
import { buildAgentFlow } from "./agent-flow";
import { syntheticSteppedAgentTrace } from "./agent-trace.test-support";
import { renderMermaid } from "./mermaid-runtime";

vi.mock("./mermaid-runtime", () => ({ renderMermaid: vi.fn() }));
function svgFor(source: string) {
  const keys = Array.from(source.matchAll(/^(n\d+)\[/gm), match => match[1]);
  const edges = Array.from(source.matchAll(/ (e\d+)@-->/g), match => match[1]);
  return `<svg><g class="nodes">${keys.map((key, i) => `<g class="node" id="flowchart-${key}-${i}" transform="translate(${100 + i * 200},100)"><rect /></g>`).join("")}</g><g class="edgePaths">${edges.map(key => `<path id="${key}" />`).join("")}</g></svg>`;
}
beforeEach(() => {
  vi.mocked(renderMermaid).mockReset();
  vi.mocked(renderMermaid).mockImplementation(async (_id, source) => ({ svg: svgFor(source) }));
  Object.defineProperty(SVGElement.prototype, "getBBox", { configurable: true, value: () => ({ x: -80, y: -40, width: 160, height: 80 }) });
});

describe("Mermaid execution diagram", () => {
  it("renders every recorded stage and its exact parent edges through Mermaid", async () => {
    const flow = buildAgentFlow(syntheticSteppedAgentTrace().spans); const onSelect = vi.fn();
    const { container } = render(<AgentFlowDiagram flow={flow} detailId="detail" onSelect={onSelect} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "배치 초기화" })).toBeEnabled());
    const diagram = screen.getByRole("group", { name: "기록된 단계와 부모 연결" });
    expect(within(diagram).getAllByRole("button")).toHaveLength(5);
    for (const span of flow.ordered) expect(container.querySelector(`[data-agent-span-id="${span.id}"]`)).toBeInTheDocument();
    const source = vi.mocked(renderMermaid).mock.calls[0][1];
    expect(source).toContain("n0 e0@--> n1"); expect(source).toContain("n0 e1@--> n2");
    expect(source).toContain("n2 e2@--> n3"); expect(source).toContain("n3 e3@--> n4");
    fireEvent.click(within(diagram).getByRole("button", { name: /위임 ·/ }));
    expect(onSelect).toHaveBeenCalledWith(flow.ordered[2].id);
  });
  it("preserves the SVG, dragged layout and zoom when selection or the same run object changes", async () => {
    const trace = syntheticSteppedAgentTrace(); const onSelect = vi.fn();
    const { rerender } = render(<AgentFlowDiagram flow={buildAgentFlow(trace.spans)} detailId="detail" onSelect={onSelect} />);
    const root = await screen.findByRole("button", { name: "에이전트 · synthetic_manager · #1" });
    fireEvent.keyDown(root, { key: "ArrowDown" });
    fireEvent.click(screen.getByRole("button", { name: "흐름도 확대" }));
    const svg = root.closest("svg")!; const box = svg.getAttribute("viewBox"); const moved = root.getAttribute("transform");
    rerender(<AgentFlowDiagram flow={buildAgentFlow([...trace.spans])} selectedId={trace.spans[0].id} detailId="detail" onSelect={onSelect} />);
    expect(screen.getByRole("button", { name: "에이전트 · synthetic_manager · #1" })).toBe(root);
    expect(root).toHaveAttribute("transform", moved); expect(svg).toHaveAttribute("viewBox", box);
    expect(renderMermaid).toHaveBeenCalledTimes(1);
    expect(root).toHaveAttribute("aria-pressed", "true");
  });
  it("uses unique render identifiers and discards a late result after unmount", async () => {
    const flow = buildAgentFlow(syntheticSteppedAgentTrace().spans);
    const first = render(<AgentFlowDiagram flow={flow} detailId="one" onSelect={vi.fn()} />);
    const second = render(<AgentFlowDiagram flow={flow} detailId="two" onSelect={vi.fn()} />);
    await waitFor(() => expect(screen.getAllByRole("group", { name: "기록된 단계와 부모 연결" })).toHaveLength(2));
    expect(vi.mocked(renderMermaid).mock.calls[0][0]).not.toBe(vi.mocked(renderMermaid).mock.calls[1][0]);
    first.unmount(); second.unmount();
    let resolve!: (result: { svg: string }) => void;
    vi.mocked(renderMermaid).mockImplementationOnce(() => new Promise(done => { resolve = done; }));
    const late = render(<AgentFlowDiagram flow={flow} detailId="late" onSelect={vi.fn()} />);
    late.unmount(); await act(async () => resolve({ svg: svgFor("n0[\"x\"]") }));
    expect(document.querySelector("g.node")).toBeNull();
  });
  it("reports renderer failure without exposing payloads or creating a false diagram", async () => {
    vi.mocked(renderMermaid).mockRejectedValueOnce(new Error("private body must not appear"));
    render(<AgentFlowDiagram flow={buildAgentFlow(syntheticSteppedAgentTrace().spans)} detailId="one" onSelect={vi.fn()} />);
    expect(await screen.findByText(/흐름도를 표시하지 못했습니다/)).toBeInTheDocument();
    expect(screen.queryByText(/private body/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "배치 초기화" })).toBeDisabled();
  });
});
