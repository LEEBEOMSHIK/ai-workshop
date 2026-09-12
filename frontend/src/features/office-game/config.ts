export const OFFICE = {
  mapKey: "office", mapUrl: "/office/maps/office.json",
  tilesKey: "office-placeholder", tilesUrl: "/office/tiles/office-placeholder.svg",
  playerTexture: "office-player", npcTexture: "office-rag-chief",
  speed: 220, interactionRadius: 100, positionInterval: 100,
  actorWidth: 48, actorHeight: 64, bodyWidth: 22, bodyHeight: 16,
  bodyOffset: { x: 13, y: 48 },
  depth: { floor: -100, wall: -10, foreground: 10000 },
} as const;
