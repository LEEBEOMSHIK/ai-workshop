import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AgentFlowDiagram } from "./AgentFlowDiagram";
import { buildAgentFlow } from "./agent-flow";
import { syntheticSteppedAgentTrace } from "./agent-trace.test-support";
import { renderMermaid } from "./mermaid-runtime";

vi.mock("./mermaid-runtime", () => ({ renderMermaid: vi.fn() }));

function svgFor(source: string) {
  const keys = Array.from(source.matchAll(/^(n\d+)\[/gm), match => match[1]);
  const edges = Array.from(source.matchAll(/ (e\d+)@-->/g), match => match[1]);
  return `<svg><g>${keys.map((key, i) => `<g class="node" id="independent-flowchart-${key}-${i}" transform="translate(${100 + i * 200},100)"><rect /></g>`).join("")}</g><g>${edges.map(key => `<path id="independent-${key}" />`).join("")}</g></svg>`;
}

function deferredRender() {
  let resolve!: (value: { svg: string }) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<{ svg: string }>((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

beforeEach(() => {
  vi.mocked(renderMermaid).mockReset();
  vi.mocked(renderMermaid).mockImplementation(async (_id, source) => ({ svg: svgFor(source) }));
  Object.defineProperty(SVGElement.prototype, "getBBox", {
    configurable: true, value: () => ({ x: -80, y: -40, width: 160, height: 80 }),
  });
});

describe("independent Mermaid refresh boundaries", () => {
  it("reports loading and disables view actions during a same-run status redraw", async () => {
    const trace = syntheticSteppedAgentTrace();
    const view = render(<AgentFlowDiagram flow={buildAgentFlow(trace.spans)} detailId="detail" onSelect={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "배치 초기화" })).toBeEnabled());
    const pending = deferredRender();
    vi.mocked(renderMermaid).mockImplementationOnce(() => pending.promise);
    const changed = trace.spans.map((span, index) => index === 0 ? { ...span, state: "running" as const } : span);
    view.rerender(<AgentFlowDiagram flow={buildAgentFlow(changed)} detailId="detail" onSelect={vi.fn()} />);
    expect(view.container.querySelector("[aria-busy]")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button", { name: "배치 초기화" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("흐름도를 그리고 있습니다.");
    await act(async () => pending.resolve({ svg: svgFor(vi.mocked(renderMermaid).mock.calls.at(-1)![1]) }));
  });

  it("replaces an old rendering error with loading when a newer revision is rendered", async () => {
    const trace = syntheticSteppedAgentTrace();
    vi.mocked(renderMermaid).mockRejectedValueOnce(new Error("synthetic failure"));
    const view = render(<AgentFlowDiagram flow={buildAgentFlow(trace.spans)} detailId="detail" onSelect={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("흐름도를 표시하지 못했습니다."));
    const pending = deferredRender();
    vi.mocked(renderMermaid).mockImplementationOnce(() => pending.promise);
    const changed = trace.spans.map((span, index) => index === 0 ? { ...span, state: "running" as const } : span);
    view.rerender(<AgentFlowDiagram flow={buildAgentFlow(changed)} detailId="detail" onSelect={vi.fn()} />);
    expect(screen.getByRole("status")).toHaveTextContent("흐름도를 그리고 있습니다.");
    expect(view.container.querySelector("[aria-busy]")).toHaveAttribute("aria-busy", "true");
    await act(async () => pending.resolve({ svg: svgFor(vi.mocked(renderMermaid).mock.calls.at(-1)![1]) }));
  });

  it("preserves a moved span by its ID through a same-run status redraw", async () => {
    const trace = syntheticSteppedAgentTrace();
    const view = render(<AgentFlowDiagram flow={buildAgentFlow(trace.spans)} detailId="detail" onSelect={vi.fn()} />);
    const original = await screen.findByRole("button", { name: "에이전트 · synthetic_manager · #1" });
    fireEvent.keyDown(original, { key: "ArrowDown", shiftKey: true });
    const moved = original.getAttribute("transform");
    const changed = trace.spans.map((span, index) => index === 0 ? { ...span, state: "running" as const } : span);
    view.rerender(<AgentFlowDiagram flow={buildAgentFlow(changed)} detailId="detail" onSelect={vi.fn()} />);
    const replacement = await screen.findByRole("button", { name: "에이전트 · synthetic_manager · #1" });
    expect(replacement).not.toBe(original);
    expect(replacement).toHaveAttribute("transform", moved);
    expect(replacement).toHaveAttribute("data-state", "running");
  });

  it("ignores an older asynchronous success and failure after a newer revision is ready", async () => {
    const trace = syntheticSteppedAgentTrace();
    const old = deferredRender();
    const middle = deferredRender();
    vi.mocked(renderMermaid).mockImplementationOnce(() => old.promise).mockImplementationOnce(() => middle.promise);
    const view = render(<AgentFlowDiagram flow={buildAgentFlow(trace.spans)} detailId="detail" onSelect={vi.fn()} />);
    const running = trace.spans.map((span, index) => index === 0 ? { ...span, state: "running" as const } : span);
    view.rerender(<AgentFlowDiagram flow={buildAgentFlow(running)} detailId="detail" onSelect={vi.fn()} />);
    const failed = trace.spans.map((span, index) => index === 0 ? { ...span, state: "failed" as const } : span);
    view.rerender(<AgentFlowDiagram flow={buildAgentFlow(failed)} detailId="detail" onSelect={vi.fn()} />);
    const current = await screen.findByRole("button", { name: "에이전트 · synthetic_manager · #1" });
    expect(current).toHaveAttribute("data-state", "failed");
    await act(async () => {
      old.resolve({ svg: "<svg><text>STALE_SYNTHETIC_RENDER</text></svg>" });
      middle.reject(new Error("STALE_SYNTHETIC_ERROR"));
    });
    expect(screen.getByRole("button", { name: "에이전트 · synthetic_manager · #1" })).toBe(current);
    expect(document.body.textContent).not.toMatch(/STALE_SYNTHETIC_/);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("detaches old SVG selection events when a revision replaces its nodes", async () => {
    const trace = syntheticSteppedAgentTrace();
    const onSelect = vi.fn();
    const view = render(<AgentFlowDiagram flow={buildAgentFlow(trace.spans)} detailId="detail" onSelect={onSelect} />);
    const original = await screen.findByRole("button", { name: "에이전트 · synthetic_manager · #1" });
    const changed = trace.spans.map((span, index) => index === 0 ? { ...span, state: "running" as const } : span);
    view.rerender(<AgentFlowDiagram flow={buildAgentFlow(changed)} detailId="detail" onSelect={onSelect} />);
    const replacement = await screen.findByRole("button", { name: "에이전트 · synthetic_manager · #1" });
    fireEvent.click(original);
    fireEvent.keyDown(original, { key: "Enter" });
    expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(replacement);
    expect(onSelect).toHaveBeenCalledExactlyOnceWith(trace.spans[0].id);
  });
});
