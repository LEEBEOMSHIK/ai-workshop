import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const css = readFileSync(new URL("../../src/shared/ui/tokens.css", import.meta.url), "utf8");
const values = new Map([...css.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map(([, key, value]) => [key, value.trim()]));

function color(name) {
  const raw = values.get(`--${name}`);
  assert.ok(raw, `Missing color ${name}`);
  assert.match(raw, /^#[0-9a-f]{6}$/i, `${name} must resolve to an opaque palette color`);
  return raw.slice(1).match(/../g).map(value => {
    const channel = parseInt(value, 16) / 255;
    return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
  }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
}

function contrast(foreground, background) {
  const a = color(foreground), b = color(background);
  return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
}

test("normal text and semantic status labels retain readable contrast", () => {
  const pairs = [
    ...["background", "surface", "surface-raised", "surface-hover", "surface-input", "surface-selected"]
      .flatMap(surface => ["text", "text-muted", "text-subtle", "accent"].map(text => [text, surface])),
    ...["success", "warning", "danger", "info"].map(tone => [tone, `${tone}-surface`]),
    ["on-accent", "accent"], ["on-accent", "accent-strong"],
    ["link-visited", "surface"],
  ];
  for (const [foreground, background] of pairs) {
    const ratio = contrast(`color-${foreground}`, `color-${background}`);
    assert.ok(ratio >= 4.5, `${foreground} on ${background}: ${ratio.toFixed(2)} < 4.5`);
  }
});

test("input boundaries and focus indicators contrast with application surfaces", () => {
  assert.ok(contrast("color-border-control", "color-surface-input") >= 3);
  for (const surface of ["background", "surface", "surface-raised", "surface-selected"]) {
    assert.ok(contrast("color-accent", `color-${surface}`) >= 3, `focus on ${surface}`);
  }
});
