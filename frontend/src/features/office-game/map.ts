import data from "../../../public/office/maps/office.json";
import type { Area, PlacedNpc, Position } from "./spatial";
export const officeMap = data;
export interface PlacedDecoration extends Area { kind: string }
export function readOfficeObjects(map: typeof data) {
  const getObjects = (name: string) => map.layers.find((layer) => layer.name === name)?.objects ?? [];
  const areas = (name: string): Area[] => getObjects(name).map((object) => ({ id: object.name, x: object.x, y: object.y, width: object.width, height: object.height }));
  const spawn = getObjects("NPC").find((object) => object.type === "spawn");
  if (!spawn) throw new Error("Office map requires a player spawn");
  return {
    spawn: { x: spawn.x, y: spawn.y } as Position,
    rooms: areas("Rooms"), collisions: areas("Collision"), interactionZones: areas("Interaction"),
    notices: getObjects("Notices").map((object) => ({ id: object.name, x: object.x, y: object.y })),
    decorations: getObjects("Decor").map((object): PlacedDecoration => ({
      id: object.name, kind: object.type, x: object.x, y: object.y, width: object.width, height: object.height,
    })),
    npcs: getObjects("NPC").filter((object) => object.type === "npc").map((object): PlacedNpc => ({ id: object.name, x: object.x, y: object.y })),
  };
}
