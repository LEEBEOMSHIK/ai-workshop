export interface Position { x: number; y: number }
export interface Area extends Position { id: string; width: number; height: number }
export interface PlacedNpc extends Position { id: string }
export function movementVector(x: number, y: number, speed: number): Position {
  const length = Math.hypot(x, y);
  return length ? { x: x / length * speed, y: y / length * speed } : { x: 0, y: 0 };
}
export function roomAt(position: Position, rooms: readonly Area[]) {
  return rooms.find((room) => position.x >= room.x && position.x < room.x + room.width && position.y >= room.y && position.y < room.y + room.height) ?? null;
}
export function nearestNpc(position: Position, npcs: readonly PlacedNpc[], radius: number) {
  return npcs.filter((npc) => Math.hypot(position.x - npc.x, position.y - npc.y) <= radius)
    .sort((a, b) => Math.hypot(position.x - a.x, position.y - a.y) - Math.hypot(position.x - b.x, position.y - b.y))[0] ?? null;
}
