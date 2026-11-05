import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const css = readFileSync(new URL("../../src/shared/ui/tokens.css", import.meta.url), "utf8");
function declarations(selector) {
  const start = css.indexOf(`${selector} {`);
  assert.notEqual(start, -1, `Missing palette ${selector}`);
  const block = css.slice(start, css.indexOf("}", start));
  return new Map([...block.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)].map(([, key, value]) => [key, value.trim()]));
}

function color(values, name) {
  const raw = values.get(`--${name}`);
  assert.ok(raw, `Missing color ${name}`);
  const alias = raw.match(/^var\(--([\w-]+)\)$/);
  if (alias) return color(values, alias[1]);
  assert.match(raw, /^#[0-9a-f]{6}$/i, `${name} must resolve to an opaque palette color`);
  return raw.slice(1).match(/../g).map(value => {
    const channel = parseInt(value, 16) / 255;
    return channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4;
  }).reduce((sum, value, index) => sum + value * [.2126, .7152, .0722][index], 0);
}

function contrast(values, foreground, background) {
  const a = color(values, foreground), b = color(values, background);
  return (Math.max(a, b) + .05) / (Math.min(a, b) + .05);
}

for (const theme of ["dark", "light"]) {
  test(`${theme} text, labels, focus and input boundaries retain contrast`, () => {
    const base = declarations(":root");
    const values = theme === "dark" ? base : new Map([...base, ...declarations(':root[data-theme="light"]')]);
    const pairs = [
      ...["background", "surface", "surface-raised", "surface-hover", "surface-input", "surface-selected"]
        .flatMap(surface => ["text", "text-muted", "text-subtle", "accent", "secondary", "highlight"].map(text => [text, surface])),
      ...["success", "warning", "danger", "info"].map(tone => [tone, `${tone}-surface`]),
      ["on-accent", "accent"], ["on-accent", "accent-strong"],
      ["on-primary", "primary"], ["on-primary", "primary-hover"],
      ...["research", "experiment", "data", "analysis", "development", "learning"].map(category => [`category-${category}`, "surface"]),
      ["link-visited", "surface"],
    ];
    for (const [foreground, background] of pairs) {
      const ratio = contrast(values, `color-${foreground}`, `color-${background}`);
      assert.ok(ratio >= 4.5, `${foreground} on ${background}: ${ratio.toFixed(2)} < 4.5`);
    }
    assert.ok(contrast(values, "color-border-control", "color-surface-input") >= 3);
    for (const surface of ["background", "surface", "surface-raised", "surface-selected", "surface-hover"]) {
      assert.ok(contrast(values, "focus-color", `color-${surface}`) >= 3, `focus on ${surface}`);
    }
  });
}
