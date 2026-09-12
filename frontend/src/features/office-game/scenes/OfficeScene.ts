import Phaser from "phaser";
import { OFFICE } from "../config";
import { createActorTextures, createOfficeDecoration } from "../assets";
import { Player } from "../entities/Player";
import { NPC } from "../entities/NPC";
import type { GameStore } from "../gameStore";
import { readOfficeObjects, type officeMap } from "../map";
import { npcCatalog, rooms } from "../npcs";
import { preparingRooms } from "../preparingRooms";
import { nearestNpc, roomAt } from "../spatial";
import { OfficeInput } from "../systems/OfficeInput";
import { onSceneExit } from "../sceneCleanup";

export class OfficeScene extends Phaser.Scene {
  private player?: Player;
  private controls?: OfficeInput;
  private world?: ReturnType<typeof readOfficeObjects>;
  private lastPosition = 0;
  constructor(private store: GameStore) { super("OfficeScene"); }
  preload() {
    this.load.tilemapTiledJSON(OFFICE.mapKey, OFFICE.mapUrl);
    this.load.svg(OFFICE.tilesKey, OFFICE.tilesUrl);
    this.load.on("loaderror", () => this.store.getState().setStatus("error"));
  }
  create() {
    if (this.store.getState().status === "error") return;
    try { this.createOffice(); }
    catch { this.store.getState().setStatus("error"); }
  }
  private createOffice() {
    const source = this.cache.tilemap.get(OFFICE.mapKey)?.data as typeof officeMap | undefined;
    if (!source) throw new Error("Missing office map");
    this.world = readOfficeObjects(source);
    const map = this.make.tilemap({ key: OFFICE.mapKey });
    const tiles = map.addTilesetImage(OFFICE.tilesKey, OFFICE.tilesKey);
    if (!tiles) throw new Error("Missing office tiles");
    const tileTexture = this.textures.get(OFFICE.tilesKey);
    for (let index = 1; index <= source.tilesets[0].tilecount; index++) {
      tileTexture.add(`tile-${index}`, 0, (index - 1) * map.tileWidth, 0, map.tileWidth, map.tileHeight);
    }
    map.createLayer("Floor", tiles)?.setDepth(OFFICE.depth.floor);
    map.createLayer("Wall", tiles)?.setDepth(OFFICE.depth.wall);
    map.createLayer("Decoration", tiles)?.setDepth(OFFICE.depth.floor + 1);
    map.createLayer("Foreground", tiles)?.setDepth(OFFICE.depth.foreground);
    const furniture = map.createLayer("Furniture", tiles);
    furniture?.forEachTile((tile) => {
      if (tile.index > 0) {
        this.add.image(tile.pixelX, tile.pixelY, OFFICE.tilesKey, `tile-${tile.index}`).setOrigin(0).setDepth(tile.pixelY + map.tileHeight);
      }
    });
    furniture?.destroy();
    for (const decoration of this.world.decorations) createOfficeDecoration(this, decoration);
    createActorTextures(this);
    this.player = new Player(this, this.world.spawn);
    this.physics.world.setBounds(0, 0, map.widthInPixels, map.heightInPixels);
    const solids = this.physics.add.staticGroup();
    for (const area of this.world.collisions) {
      const solid = this.add.rectangle(area.x + area.width / 2, area.y + area.height / 2, area.width, area.height, 0, 0);
      solids.add(solid);
    }
    this.physics.add.collider(this.player.sprite, solids);
    for (const placement of this.world.npcs) {
      const definition = npcCatalog.find((npc) => npc.id === placement.id);
      if (!definition) continue;
      const npc = new NPC(this, placement, definition, (id) => this.store.getState().selectNpc(id));
      this.physics.add.collider(this.player.sprite, npc.sprite);
    }
    for (const room of this.world.rooms) {
      this.add.text(room.x + room.width / 2, room.y + (room.id === "lobby" ? 76 : 20), rooms[room.id as keyof typeof rooms] ?? room.id, { fontFamily: "sans-serif", fontSize: "20px", color: "#314956", fontStyle: "bold" }).setOrigin(0.5).setDepth(0);
    }
    for (const notice of this.world.notices) {
      if (!preparingRooms.some((room) => room.id === notice.id)) continue;
      this.add.zone(notice.x, notice.y + 16, 192, 112).setDepth(notice.y + 120)
        .setInteractive({ useHandCursor: true })
        .on("pointerdown", () => this.store.getState().selectNotice(notice.id));
    }
    this.add.text(768, 1180, "↓ 준비 공간 · 관리자 모집 중", { fontFamily: "sans-serif", fontSize: "19px", color: "#46645b", fontStyle: "bold" }).setOrigin(0.5).setDepth(0);
    this.add.text(768, 940, "AI WORKSHOP", { fontFamily: "monospace", fontSize: "30px", color: "#7a8172", letterSpacing: 5 }).setOrigin(0.5).setDepth(0);
    this.add.text(768, 782, "← FOUNDER        RAG LAB →", { fontFamily: "monospace", fontSize: "17px", color: "#58675e" }).setOrigin(0.5).setDepth(0);
    const canvas = this.game.canvas;
    canvas.tabIndex = 0;
    canvas.setAttribute("aria-label", "AI 연구소 이동 공간. WASD 또는 방향키 이동, E 대화. Tab으로 메뉴 이동.");
    canvas.setAttribute("role", "application");
    this.controls = new OfficeInput(canvas, () => this.store.getState().openDialogue());
    const focusCanvas = () => { if (!this.store.getState().dialogueOpen) canvas.focus({ preventScroll: true }); };
    canvas.addEventListener("pointerdown", focusCanvas);
    const unsubscribe = this.store.subscribe((state, previous) => {
      if (state.dialogueOpen !== previous.dialogueOpen) { this.controls?.clear(); this.player?.move({ x: 0, y: 0 }); }
    });
    onSceneExit(this.events, () => { unsubscribe(); this.controls?.destroy(); canvas.removeEventListener("pointerdown", focusCanvas); });
    this.cameras.main.setBounds(0, 0, map.widthInPixels, map.heightInPixels).startFollow(this.player.sprite, true, 0.12, 0.12);
    this.store.getState().updateWorld(this.world.spawn, "lobby");
    this.store.getState().setStatus("ready");
  }
  update(time: number) {
    if (!this.player || !this.controls || !this.world) return;
    const state = this.store.getState();
    const active = !state.dialogueOpen && !document.hidden && document.activeElement === this.game.canvas;
    this.player.move(active ? this.controls.direction() : { x: 0, y: 0 });
    const position = { x: this.player.sprite.x, y: this.player.sprite.y };
    const npc = nearestNpc(position, this.world.npcs, OFFICE.interactionRadius);
    const zone = npc && this.world.interactionZones.find((area) => area.id === npc.id && roomAt(position, [area]));
    state.setNearbyNpc(zone && npc ? npc.id : null);
    const notice = this.world.notices.find((entry) =>
      Math.hypot(position.x - entry.x, position.y - entry.y) <= OFFICE.interactionRadius &&
      roomAt(position, this.world!.rooms)?.id === entry.id);
    state.setNearbyNotice(notice?.id ?? null);
    if (time - this.lastPosition >= OFFICE.positionInterval) {
      state.updateWorld(position, roomAt(position, this.world.rooms)?.id ?? "lobby");
      this.lastPosition = time;
    }
  }
}
