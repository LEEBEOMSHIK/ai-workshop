import { fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { bindMermaidGraph } from "./mermaid-graph-interaction";

function fixture() {
  document.body.innerHTML = `<svg viewBox="0 0 500 300"><g class="nodes"><g id="agent-render-1-flowchart-n0-0" class="node" transform="translate(100,100)"><rect width="80" height="40"/></g><g id="agent-render-1-flowchart-n1-1" class="node" transform="translate(300,100)"><rect width="80" height="40"/></g></g><g><path id="agent-render-1-e0" /></g></svg>`;
  const svg = document.querySelector("svg")!;
  Object.defineProperty(svg, "getBoundingClientRect", { value: () => ({ left: 0, top: 0, width: 500, height: 300 }) });
  for (const node of svg.querySelectorAll<SVGGElement>(".node")) {
    Object.defineProperty(node, "getBBox", { value: () => ({ x: -40, y: -20, width: 80, height: 40 }) });
  }
  const onSelect = vi.fn(); const positions = new Map<string, { x: number; y: number }>();
  const graph = { source: "", nodes: [{ key: "n0", spanId: "one", label: "first" }, { key: "n1", spanId: "two", label: "second" }],
    edges: [{ key: "e0", sourceId: "one", targetId: "two" }] };
  const controller = bindMermaidGraph(svg, graph, positions, onSelect);
  return { svg, onSelect, positions, controller, node: svg.querySelector<SVGGElement>(".node")!, edge: svg.querySelector("path")! };
}
afterEach(() => { document.body.replaceChildren(); vi.unstubAllGlobals(); });

describe("interactive Mermaid geometry", () => {
  it("opens exactly once when pointer capture retargets the browser click to the SVG", () => {
    class Pointer extends MouseEvent { pointerId = 1; }
    vi.stubGlobal("PointerEvent", Pointer);
    const { node, svg, onSelect, controller } = fixture();
    fireEvent.pointerDown(node, { clientX: 100, clientY: 100, button: 0 });
    fireEvent.pointerUp(svg, { clientX: 100, clientY: 100 });
    fireEvent.click(svg);
    expect(onSelect).toHaveBeenCalledExactlyOnceWith("one");
    controller.destroy();
  });
  it("opens on click and Enter but arrow movement updates only the saved node and connected edge", () => {
    const { node, edge, onSelect, positions, controller } = fixture();
    fireEvent.click(node); expect(onSelect).toHaveBeenCalledWith("one");
    fireEvent.keyDown(node, { key: "Enter" }); expect(onSelect).toHaveBeenCalledTimes(2);
    const before = edge.getAttribute("d");
    fireEvent.keyDown(node, { key: "ArrowDown" });
    expect(positions.get("one")?.y).toBe(116);
    expect(edge.getAttribute("d")).not.toBe(before);
    expect(onSelect).toHaveBeenCalledTimes(2);
    controller.destroy();
    fireEvent.keyDown(node, { key: "Enter" }); expect(onSelect).toHaveBeenCalledTimes(2);
  });
  it("keeps node positions across rebinds, fits without resetting, and resets explicitly", () => {
    const { node, positions, controller, svg } = fixture();
    fireEvent.keyDown(node, { key: "ArrowRight", shiftKey: true });
    const moved = positions.get("one");
    controller.zoom(0.8); const zoomed = svg.getAttribute("viewBox");
    controller.fit(); expect(positions.get("one")).toEqual(moved); expect(svg.getAttribute("viewBox")).not.toBe(zoomed);
    controller.reset(); expect(positions.size).toBe(0); expect(node.getAttribute("transform")).toBe("translate(100, 100)");
    controller.destroy();
  });
  it("keeps pointer drags distinct from clicking and rolls back pointer cancellation", () => {
    class Pointer extends MouseEvent { pointerId: number; constructor(type: string, init: MouseEventInit & { pointerId?: number }) { super(type, init); this.pointerId = init.pointerId ?? 1; } }
    vi.stubGlobal("PointerEvent", Pointer);
    const { node, positions, controller, onSelect } = fixture();
    fireEvent.pointerDown(node, { clientX: 100, clientY: 100, pointerId: 1, button: 0 });
    fireEvent.pointerMove(node, { clientX: 140, clientY: 120, pointerId: 1 });
    expect(positions.get("one")?.x).toBeGreaterThan(100);
    fireEvent.pointerUp(node, { clientX: 140, clientY: 120, pointerId: 1 });
    fireEvent.click(node); expect(onSelect).not.toHaveBeenCalled();
    fireEvent.click(node); expect(onSelect).toHaveBeenCalledWith("one");
    const before = { ...positions.get("one")! };
    fireEvent.pointerDown(node, { clientX: 140, clientY: 120, pointerId: 2, button: 0 });
    fireEvent.pointerMove(node, { clientX: 190, clientY: 170, pointerId: 2 });
    fireEvent.pointerCancel(node, { pointerId: 2 }); expect(positions.get("one")).toEqual(before);
    controller.destroy();
  });
});
