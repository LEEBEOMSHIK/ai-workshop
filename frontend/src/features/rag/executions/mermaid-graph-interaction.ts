import type { MermaidAgentGraph } from "./mermaid-agent-graph";
import { edgePath, fitBounds, type Bounds, type NodeRect, type Point } from "./mermaid-graph-geometry";

export type GraphController = { zoom: (factor: number) => void; fit: () => void; reset: () => void; destroy: () => void };
type PlacedNode = { element: SVGGElement; bounds: NodeRect; initial: Point; offset: Point };

// Mermaid lays out this flat flowchart in one coordinate space. Keep its real SVG
// nodes, labels, arrow markers and styles; move only node translations and edges.
export function bindMermaidGraph(svg: SVGSVGElement, graph: MermaidAgentGraph,
  positions: Map<string, Point>, onSelect: (id: string) => void,
  camera?: { current: Bounds | undefined },
): GraphController {
  const nodes = new Map<string, PlacedNode>();
  const candidates = Array.from(svg.querySelectorAll<SVGGElement>("g.node"));
  for (const entry of graph.nodes) {
    const element = candidates.find(node => new RegExp(`(?:^|-)flowchart-${entry.key}-\\d+$`).test(node.id));
    if (!element) throw new Error("diagram_node_missing");
    const translation = /translate\(\s*([-\d.e+]+)[,\s]+([-\d.e+]+)\s*\)/i.exec(element.getAttribute("transform") ?? "");
    if (!translation) throw new Error("diagram_position_missing");
    const box = element.getBBox();
    const offset = { x: box.x + box.width / 2, y: box.y + box.height / 2 };
    const initial = { x: Number(translation[1]) + offset.x, y: Number(translation[2]) + offset.y };
    const location = positions.get(entry.spanId) ?? initial;
    nodes.set(entry.spanId, { element, initial, offset, bounds: { ...location, width: box.width, height: box.height } });
    element.setAttribute("data-agent-span-id", entry.spanId);
    element.setAttribute("role", "button"); element.setAttribute("tabindex", "0");
    element.setAttribute("aria-haspopup", "dialog"); element.setAttribute("aria-label", entry.label);
  }
  const edges = graph.edges.map(edge => ({ ...edge,
    element: Array.from(svg.querySelectorAll<SVGPathElement>("path")).find(path => path.id === edge.key || path.id.endsWith(`-${edge.key}`)),
  }));
  if (edges.some(edge => !edge.element)) throw new Error("diagram_edge_missing");
  function draw() {
    for (const { element, bounds, offset } of nodes.values()) {
      element.setAttribute("transform", `translate(${bounds.x - offset.x}, ${bounds.y - offset.y})`);
    }
    for (const edge of edges) edge.element!.setAttribute("d", edgePath(nodes.get(edge.sourceId)!.bounds, nodes.get(edge.targetId)!.bounds));
  }
  let view: Bounds = camera?.current ?? fitBounds([...nodes.values()].map(node => node.bounds));
  function setView(next: Bounds) {
    view = next; if (camera) camera.current = next;
    svg.setAttribute("viewBox", `${view.x} ${view.y} ${view.width} ${view.height}`);
  }
  function fit() { setView(fitBounds([...nodes.values()].map(node => node.bounds))); }
  function point(event: PointerEvent): Point {
    const matrix = svg.getScreenCTM?.();
    if (matrix && svg.createSVGPoint) {
      const source = svg.createSVGPoint(); source.x = event.clientX; source.y = event.clientY;
      const result = source.matrixTransform(matrix.inverse()); return { x: result.x, y: result.y };
    }
    const box = svg.getBoundingClientRect();
    const scale = Math.min(box.width / view.width, box.height / view.height) || 1;
    return { x: view.x + (event.clientX - box.left - (box.width - view.width * scale) / 2) / scale,
      y: view.y + (event.clientY - box.top - (box.height - view.height * scale) / 2) / scale };
  }
  function idAt(target: EventTarget | null) {
    return target instanceof Element ? target.closest("[data-agent-span-id]")?.getAttribute("data-agent-span-id") : null;
  }
  type Drag = { pointerId: number; id: string | null; start: Point; client: Point; origin: Point; view: Bounds; moved: boolean; wasSaved: boolean };
  let drag: Drag | null = null;
  let suppressClick = false;
  let clickTimer: ReturnType<typeof setTimeout> | undefined;
  function suppress() {
    suppressClick = true; clearTimeout(clickTimer); clickTimer = setTimeout(() => { suppressClick = false; }, 250);
  }
  function down(event: PointerEvent) {
    if (event.button !== 0 || drag) return;
    const id = idAt(event.target) ?? null; const node = id ? nodes.get(id) : undefined;
    drag = { pointerId: event.pointerId, id, start: point(event), client: { x: event.clientX, y: event.clientY },
      origin: node ? { x: node.bounds.x, y: node.bounds.y } : { x: view.x, y: view.y }, view: { ...view },
      moved: false, wasSaved: id ? positions.has(id) : false };
    node?.element.focus(); svg.setPointerCapture?.(event.pointerId);
  }
  function move(event: PointerEvent) {
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (!drag.moved && Math.hypot(event.clientX - drag.client.x, event.clientY - drag.client.y) < 4) return;
    drag.moved = true; event.preventDefault();
    const current = point(event); const dx = current.x - drag.start.x, dy = current.y - drag.start.y;
    if (drag.id) {
      const node = nodes.get(drag.id)!; node.bounds.x = drag.origin.x + dx; node.bounds.y = drag.origin.y + dy;
      positions.set(drag.id, { x: node.bounds.x, y: node.bounds.y }); draw();
    } else {
      setView({ ...view, x: view.x - dx, y: view.y - dy });
    }
  }
  function up(event: PointerEvent) {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const selectedId = !drag.moved ? drag.id : null;
    // Pointer capture retargets native click to the SVG. Resolve a tap from the
    // original node, then consume its compatibility click to avoid double opens.
    if (drag.moved || selectedId) suppress(); drag = null;
    if (svg.hasPointerCapture?.(event.pointerId)) svg.releasePointerCapture(event.pointerId);
    if (selectedId) onSelect(selectedId);
  }
  function cancel(event: PointerEvent) {
    if (!drag || drag.pointerId !== event.pointerId) return;
    if (drag.id) {
      Object.assign(nodes.get(drag.id)!.bounds, drag.origin);
      if (drag.wasSaved) positions.set(drag.id, drag.origin); else positions.delete(drag.id);
      draw();
    } else setView(drag.view);
    if (drag.moved) suppress(); drag = null;
  }
  function click(event: MouseEvent) {
    if (suppressClick) { suppressClick = false; event.preventDefault(); return; }
    const id = idAt(event.target); if (id) onSelect(id);
  }
  function key(event: KeyboardEvent) {
    const id = idAt(event.target); if (!id) return;
    if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(id); return; }
    const directions: Record<string, Point> = { ArrowLeft: { x: -1, y: 0 }, ArrowRight: { x: 1, y: 0 }, ArrowUp: { x: 0, y: -1 }, ArrowDown: { x: 0, y: 1 } };
    const direction = directions[event.key]; if (!direction) return;
    event.preventDefault(); const step = event.shiftKey ? 48 : 16; const node = nodes.get(id)!;
    node.bounds.x += direction.x * step; node.bounds.y += direction.y * step;
    positions.set(id, { x: node.bounds.x, y: node.bounds.y }); draw();
  }
  const listeners = { pointerdown: down, pointermove: move, pointerup: up, pointercancel: cancel, lostpointercapture: cancel, click, keydown: key };
  for (const [name, listener] of Object.entries(listeners)) svg.addEventListener(name, listener as EventListener);
  draw(); setView(view);
  return {
    zoom(factor) {
      const width = Math.max(160, Math.min(20000, view.width * factor)); const height = view.height * width / view.width;
      setView({ x: view.x + (view.width - width) / 2, y: view.y + (view.height - height) / 2, width, height });
    },
    fit,
    reset() { positions.clear(); for (const node of nodes.values()) Object.assign(node.bounds, node.initial); draw(); fit(); },
    destroy() { clearTimeout(clickTimer); for (const [name, listener] of Object.entries(listeners)) svg.removeEventListener(name, listener as EventListener); },
  };
}
