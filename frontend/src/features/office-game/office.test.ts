import { describe, expect, it } from "vitest";
import { createGameStore } from "./gameStore";
import { movementVector, roomAt, nearestNpc } from "./spatial";
import { officeMap, readOfficeObjects } from "./map";
import { mountGame } from "./lifecycle";
import { npcCatalog } from "./npcs";

describe("office spatial contracts", () => {
  it("normalizes diagonal movement without accelerating", () => {
    expect(movementVector(1, 1, 100).x).toBeCloseTo(70.7107);
    expect(movementVector(0, 0, 100)).toEqual({ x: 0, y: 0 });
  });
  it("loads walkable spawn, room boundaries and a bounded NPC interaction", () => {
    const world = readOfficeObjects(officeMap);
    expect(roomAt(world.spawn, world.rooms)?.id).toBe("lobby");
    expect(roomAt({ x: 480, y: 360 }, world.rooms)?.id).toBe("founder");
    expect(roomAt({ x: 1120, y: 400 }, world.rooms)?.id).toBe("rag");
    expect(nearestNpc({ x: 1120, y: 470 }, world.npcs, 100)?.id).toBe("rag-chief");
    expect(nearestNpc(world.spawn, world.npcs, 100)).toBeNull();
    for (const wall of world.collisions) {
      expect(world.spawn.x > wall.x && world.spawn.x < wall.x + wall.width && world.spawn.y > wall.y && world.spawn.y < wall.y + wall.height).toBe(false);
    }
    const floor = officeMap.layers.find((layer) => layer.name === "Floor");
    expect(floor && "data" in floor && floor.data?.length).toBe(officeMap.width * officeMap.height);
  });
  it("keeps the declared lobby-to-lab route clear of visible furniture", () => {
    const navigation = officeMap.layers.find((layer) => layer.name === "Navigation");
    const route = navigation && "objects" in navigation
      ? navigation.objects?.find((object) => object.name === "primary-route")
      : undefined;
    expect(route).toMatchObject({ type: "walkable" });

    const collision = officeMap.layers.find((layer) => layer.name === "Collision");
    const blockers = collision && "objects" in collision
      ? collision.objects ?? []
      : [];
    expect(blockers.every((area) => !route ||
      area.x + area.width <= route.x || route.x + route.width <= area.x ||
      area.y + area.height <= route.y || route.y + route.height <= area.y)).toBe(true);
  });
  it("links every visible furniture tile to its matching collision footprint", () => {
    const furniture = officeMap.layers.find((layer) => layer.name === "Furniture");
    const collision = officeMap.layers.find((layer) => layer.name === "Collision");
    const colliders = collision && "objects" in collision
      ? collision.objects?.filter((object) => object.type === "furniture") ?? []
      : [];
    const placedTiles = furniture && "data" in furniture
      ? furniture.data?.flatMap((tile, index) => tile ? [{ tile, index }] : []) ?? []
      : [];

    for (const placement of placedTiles) {
      const collider = colliders.find((area) => area.properties?.some((property) =>
        property.name === "tileIndex" && Number(property.value) === placement.index));
      expect(collider, `missing collider for furniture cell ${placement.index}`).toMatchObject({
        x: placement.index % officeMap.width * officeMap.tilewidth,
        width: officeMap.tilewidth,
      });
    }
  });
  it("provides foot-sized routes from the lobby through each door to each registered NPC", () => {
    const world = readOfficeObjects(officeMap);
    const routes = [
      [{ x: 768, y: 1040 }, { x: 768, y: 760 }, { x: 480, y: 760 }, { x: 480, y: 440 }],
      [{ x: 768, y: 1040 }, { x: 768, y: 760 }, { x: 1120, y: 760 }, { x: 1120, y: 480 }],
    ];
    for (const route of routes) for (let index = 1; index < route.length; index++) {
      const a = route[index - 1], b = route[index];
      for (let t = 0; t <= 1; t += 0.025) {
        const x = a.x + (b.x - a.x) * t, y = a.y + (b.y - a.y) * t;
        expect(world.collisions.some((solid) => x + 11 > solid.x && x - 11 < solid.x + solid.width && y > solid.y && y - 16 < solid.y + solid.height), `blocked at ${x},${y}`).toBe(false);
      }
    }
    for (const npc of world.npcs) expect(roomAt(npc, world.rooms)?.id).toBe(npcCatalog.find((entry) => entry.id === npc.id)?.room);
    const limit = officeMap.tilesets[0].tilecount;
    for (const layer of officeMap.layers) if (layer.data) expect(layer.data.every((gid) => gid >= 0 && gid <= limit)).toBe(true);
  });
  it("gives each collidable reception, lounge and lab furnishing a named footprint", () => {
    const decor = officeMap.layers.find((layer) => layer.name === "Decor");
    const objects = decor && "objects" in decor ? decor.objects ?? [] : [];
    const requiredCollidableKinds = new Set(["reception", "sofa", "coffee-table", "whiteboard", "server-rack", "executive-desk", "workbench", "bookcase", "plant", "direction-board", "recruitment-board", "knowledge-board", "study-board"]);
    const kinds = objects.map((object) => object.type);
    expect(kinds).toEqual(expect.arrayContaining([
      "reception", "sofa", "coffee-table", "whiteboard", "server-rack", "monitor-bank",
    ]));

    const collision = officeMap.layers.find((layer) => layer.name === "Collision");
    const colliders = collision && "objects" in collision ? collision.objects ?? [] : [];
    for (const object of objects.filter((entry) => requiredCollidableKinds.has(entry.type))) {
      expect(object.properties?.some((property) => property.name === "collides" && property.value === true),
        `${object.name} must declare its collision contract`).toBe(true);
      expect(colliders.some((area) => area.properties?.some((property) =>
        property.name === "visualId" && property.value === object.name)),
      `missing named footprint for ${object.name}`).toBe(true);
    }
  });
});

describe("session state bridge", () => {
  it("selects only registered visible-world NPC identities while ready and never replaces an open dialogue", () => {
    const store = createGameStore();
    expect(typeof store.getState().selectNpc).toBe("function");
    store.getState().selectNpc("founder");
    expect(store.getState().dialogueOpen).toBe(false);
    store.getState().setStatus("ready");
    store.getState().selectNpc("unknown");
    expect(store.getState().dialogueOpen).toBe(false);
    store.getState().selectNpc("founder");
    expect(store.getState().selectedNPC).toBe("founder");
    store.getState().selectNpc("rag-chief");
    expect(store.getState().selectedNPC).toBe("founder");
    store.getState().closeDialogue();
    store.getState().setStatus("error");
    store.getState().selectNpc("rag-chief");
    expect(store.getState().dialogueOpen).toBe(false);
  });
  it("opens the registered RAG route and keeps Founder directions public and separate from navigation", () => {
    const founder = npcCatalog.find((npc) => npc.id === "founder");
    expect(founder).toBeDefined();
    expect(founder?.directions.map((direction) => direction.recipient)).toEqual(["RAG 총괄", "문서 처리 담당", "평가 담당"]);
    expect(npcCatalog.find((npc) => npc.id === "rag-chief")?.href).toBe("/labs/rag");
  });
  it("only opens nearby registered NPCs and blocks movement until closed", () => {
    const store = createGameStore();
    store.getState().setStatus("ready");
    store.getState().openDialogue();
    expect(store.getState().dialogueOpen).toBe(false);
    store.getState().setNearbyNpc("unknown");
    expect(store.getState().interactionAvailable).toBe(false);
    store.getState().setNearbyNpc("rag-chief");
    store.getState().openDialogue();
    expect(store.getState().selectedNPC).toBe("rag-chief");
    expect(store.getState().dialogueOpen).toBe(true);
    store.getState().closeDialogue();
    expect(store.getState().dialogueOpen).toBe(false);
    expect(createGameStore().getState().selectedNPC).toBeNull();
  });
  it("clears the prompt when walking away", () => {
    const store = createGameStore();
    store.getState().setNearbyNpc("rag-chief");
    store.getState().setNearbyNpc(null);
    expect(store.getState().interactionAvailable).toBe(false);
  });
});

describe("async game lifecycle", () => {
  it("does not create a game after an unmounted async import resolves", async () => {
    let resolve!: (value: () => { destroy: () => void }) => void;
    let creates = 0;
    const pending = new Promise<() => { destroy: () => void }>((done) => { resolve = done; });
    const dispose = mountGame(() => pending, () => undefined);
    dispose();
    resolve(() => { creates++; return { destroy() {} }; });
    await pending;
    await Promise.resolve();
    expect(creates).toBe(0);
  });
  it("destroys exactly one mounted instance and reports loading failure", async () => {
    let destroys = 0;
    const dispose = mountGame(async () => () => ({ destroy() { destroys++; } }), () => undefined);
    await Promise.resolve();
    dispose(); dispose();
    expect(destroys).toBe(1);
    let failed = false;
    mountGame(async () => { throw new Error("unavailable"); }, () => { failed = true; });
    await Promise.resolve(); await Promise.resolve();
    expect(failed).toBe(true);
  });
});
