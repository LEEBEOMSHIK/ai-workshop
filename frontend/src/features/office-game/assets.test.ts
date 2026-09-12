import type Phaser from "phaser";
import { expect, it } from "vitest";
import { createActorTextures } from "./assets";
import { OFFICE } from "./config";

it("registers direction-local contact/pass/opposite/pass loops and existing NPC idle cell", () => {
  const animations: Phaser.Types.Animations.Animation[] = [];
  const cells = new Map<string, number[]>();
  // Phaser canvas/animation registration boundary; real artwork and frame assembly run.
  const scene = {
    textures: { createCanvas(key: string) {
      const frames: number[] = []; cells.set(key, frames);
      return { context: { fillStyle: "", fillRect() {} }, add(frame: number) { frames.push(frame); }, refresh() {} };
    } },
    anims: {
      create(config: Phaser.Types.Animations.Animation) { animations.push(config); },
      generateFrameNumbers(key: string, config: { start?: number; end?: number; frames?: number[] }) {
        return (config.frames ?? Array.from({ length: config.end! - config.start! + 1 }, (_, i) => config.start! + i)).map(frame => ({ key, frame }));
      },
    },
  } as unknown as Phaser.Scene;
  createActorTextures(scene);
  for (const [direction, expected] of [["down", [0, 1, 2, 1]], ["up", [3, 4, 5, 4]], ["left", [6, 7, 8, 7]], ["right", [9, 10, 11, 10]]] as const) {
    const walk = animations.find(a => a.key === `walk-${direction}`)!;
    expect(walk.frames).toEqual(expected.map(frame => ({ key: OFFICE.playerTexture, frame })));
    expect(walk.repeat).toBe(-1);
    expect(animations.find(a => a.key === `idle-${direction}`)?.frames).toEqual([{ key: OFFICE.playerTexture, frame: expected[1] }]);
    for (const frame of expected) expect(cells.get(OFFICE.playerTexture)).toContain(frame);
  }
  expect(cells.get("office-founder")).toContain(1);
  expect(cells.get(OFFICE.npcTexture)).toContain(1);
});
