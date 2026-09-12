import type Phaser from "phaser";
import { OFFICE } from "./config";
import { humanPixels, type HumanIdentity } from "../public-labs/human-art";
export { createOfficeDecoration } from "./office-decor";

const ACTORS: { key: string; identity: HumanIdentity }[] = [
  { key: OFFICE.playerTexture, identity: "visitor" },
  { key: "office-founder", identity: "founder" },
  { key: OFFICE.npcTexture, identity: "rag-chief" },
];

export function createActorTextures(scene: Phaser.Scene) {
  for (const actor of ACTORS) {
    const texture = scene.textures.createCanvas(actor.key, OFFICE.actorWidth * 12, OFFICE.actorHeight);
    if (!texture) throw new Error("Cannot create office sprites");
    for (let frame = 0; frame < 12; frame++) {
      const step = frame % 3 - 1;
      for (const [color, x, y, width, height] of humanPixels(actor.identity, Math.floor(frame / 3), step)) {
        texture.context.fillStyle = color;
        texture.context.fillRect(frame * OFFICE.actorWidth + x, y, width, height);
      }
      texture.add(frame, 0, frame * OFFICE.actorWidth, 0, OFFICE.actorWidth, OFFICE.actorHeight);
    }
    texture.refresh();
  }
  ["down", "up", "left", "right"].forEach((direction, index) => {
    scene.anims.create({ key: `idle-${direction}`, frames: [{ key: OFFICE.playerTexture, frame: index * 3 + 1 }], frameRate: 1 });
    // Return through the passing pose before the next contact; cell 1 stays
    // the neutral front pose used by static NPCs as well as idle-down.
    scene.anims.create({ key: `walk-${direction}`, frames: scene.anims.generateFrameNumbers(OFFICE.playerTexture, { frames: [index * 3, index * 3 + 1, index * 3 + 2, index * 3 + 1] }), frameRate: 9, repeat: -1 });
  });
}
