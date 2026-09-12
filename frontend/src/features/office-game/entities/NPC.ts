import Phaser from "phaser";
import { OFFICE } from "../config";
import type { PlacedNpc } from "../spatial";
import type { OfficeNpc } from "../npcs";
export class NPC {
  readonly sprite: Phaser.Physics.Arcade.Sprite;
  constructor(scene: Phaser.Scene, npc: PlacedNpc, definition: OfficeNpc, select: (id: string) => void) {
    this.sprite = scene.physics.add.staticSprite(npc.x, npc.y, `office-${definition.asset}`, 1).setOrigin(0.5, 1).setDepth(npc.y);
    this.sprite.refreshBody();
    this.sprite.setSize(OFFICE.bodyWidth, OFFICE.bodyHeight).setOffset(OFFICE.bodyOffset.x, OFFICE.bodyOffset.y);
    this.sprite.setInteractive({ useHandCursor: true }).on("pointerdown", () => select(npc.id));
    scene.add.text(npc.x, npc.y - 76, definition.name, { fontFamily: "sans-serif", fontSize: "16px", color: "#fff3d7", backgroundColor: "#203f54", padding: { x: 12, y: 7 } }).setOrigin(0.5).setDepth(OFFICE.depth.foreground);
  }
}
