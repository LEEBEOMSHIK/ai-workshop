import { describe, expect, it } from "vitest";
import { humanPalettes, humanPixels, type HumanIdentity } from "./human-art";

// Composite in painter order: assertions concern visible pixels, not hidden rectangles.
function raster(identity: HumanIdentity, direction = 0, step = 0) {
  const rows = Array.from({ length: 64 }, () => Array<string>(48).fill(""));
  for (const [color, x, y, w, h] of humanPixels(identity, direction, step)) {
    for (let py = y; py < y + h; py++) for (let px = x; px < x + w; px++) rows[py][px] = color;
  }
  return rows;
}

describe("directional human artwork", () => {
  it("turns the torso into a narrower profile in both side views", () => {
    const front = raster("founder")[35].filter(Boolean).length;
    for (const direction of [2, 3]) expect(raster("founder", direction)[35].filter(Boolean).length).toBeLessThan(front - 8);
  });
  it("shows hair and a closed coat back without face, front shirt or tie", () => {
    for (const identity of Object.keys(humanPalettes) as HumanIdentity[]) {
      const back = raster(identity, 1);
      expect(back.slice(14, 24).flatMap(row => row.slice(15, 34))).not.toContain(humanPalettes[identity].skin);
      expect(back.slice(30, 47).flat()).not.toContain(humanPalettes[identity].shirt);
      expect(back.flat()).not.toContain("#29383c");
      expect(back.flat()).not.toContain("#b5804e");
      expect(back.slice(30, 47).flat()).not.toContain("#ead5ac");
    }
  });
  it("swings profile feet horizontally through the passing pose", () => {
    for (const direction of [2, 3]) {
      const shoeXs = (step: number) => raster("founder", direction, step).slice(56, 63).flatMap(row => row.flatMap((color, x) => color === "#172630" ? [x] : []));
      const passing = shoeXs(0);
      for (const step of [-1, 1]) {
        const contact = shoeXs(step);
        expect(Math.max(...contact) - Math.min(...contact)).toBeGreaterThan(Math.max(...passing) - Math.min(...passing) + 4);
      }
      expect(raster("founder", direction, -1)).not.toEqual(raster("founder", direction, 1));
    }
  });
  it("keeps every pose within its cell and the shadow anchored", () => {
    for (const identity of Object.keys(humanPalettes) as HumanIdentity[]) for (const direction of [0, 1, 2, 3]) for (const step of [-1, 0, 1]) {
      const pixels = humanPixels(identity, direction, step);
      expect(pixels.filter(([color]) => color === "#22313235")).toEqual([["#22313235", 9, 60, 31, 3]]);
      for (const [, x, y, w, h] of pixels) {
        expect(x).toBeGreaterThanOrEqual(0); expect(y).toBeGreaterThanOrEqual(0);
        expect(x + w).toBeLessThanOrEqual(48); expect(y + h).toBeLessThanOrEqual(64);
      }
    }
  });
});
