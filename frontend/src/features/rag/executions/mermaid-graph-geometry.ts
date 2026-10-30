export type Point = { x: number; y: number };
export type NodeRect = Point & { width: number; height: number };
export type Bounds = Point & { width: number; height: number };

function boundary(rect: NodeRect, toward: Point): Point {
  const dx = toward.x - rect.x, dy = toward.y - rect.y;
  if (!dx && !dy) return { x: rect.x + rect.width / 2, y: rect.y };
  const scale = 1 / Math.max(Math.abs(dx) / Math.max(1, rect.width / 2), Math.abs(dy) / Math.max(1, rect.height / 2));
  return { x: rect.x + dx * scale, y: rect.y + dy * scale };
}
const rounded = (value: number) => Math.round(value * 100) / 100;

export function edgePath(source: NodeRect, target: NodeRect) {
  const start = boundary(source, target), end = boundary(target, source);
  return `M ${rounded(start.x)} ${rounded(start.y)} L ${rounded(end.x)} ${rounded(end.y)}`;
}

export function moveByClientDelta(origin: Point, delta: Point, scale: number): Point {
  return { x: origin.x + delta.x / scale, y: origin.y + delta.y / scale };
}

export function fitBounds(nodes: NodeRect[], margin = 48): Bounds {
  if (!nodes.length) return { x: 0, y: 0, width: 800, height: 400 };
  const left = Math.min(...nodes.map(node => node.x - node.width / 2));
  const top = Math.min(...nodes.map(node => node.y - node.height / 2));
  const right = Math.max(...nodes.map(node => node.x + node.width / 2));
  const bottom = Math.max(...nodes.map(node => node.y + node.height / 2));
  return { x: left - margin, y: top - margin, width: Math.max(1, right - left + margin * 2), height: Math.max(1, bottom - top + margin * 2) };
}
