import Phaser from "phaser";
import type { GameStore } from "./gameStore";
import { OfficeScene } from "./scenes/OfficeScene";
export function createPhaserGame(parent: HTMLDivElement, store: GameStore) {
  const game = new Phaser.Game({
    type: Phaser.AUTO, parent, backgroundColor: "#243e43", pixelArt: true,
    width: parent.clientWidth || 960, height: parent.clientHeight || 640,
    scale: { mode: Phaser.Scale.NONE },
    physics: { default: "arcade", arcade: { gravity: { x: 0, y: 0 }, debug: false } },
    input: { keyboard: false }, scene: [new OfficeScene(store)],
  });
  const resize = new ResizeObserver(() => {
    if (parent.clientWidth && parent.clientHeight) game.scale.resize(parent.clientWidth, parent.clientHeight);
  });
  resize.observe(parent);
  return { destroy() { resize.disconnect(); game.destroy(true); } };
}
