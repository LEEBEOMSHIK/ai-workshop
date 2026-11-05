// Run from frontend: node tests/ui-style/button-hover-browser.mjs
import assert from "node:assert/strict";
import { chromium } from "@playwright/test";
import { createPreviewServer } from "./design-system-preview.mjs";

const variants = ["기본 실행", "보조 동작", "조용한 동작", "삭제 예시"];
const legacy = "현재 배치 검사";
const buttonLink = "간편 설정 링크";
const selected = "선택된 대화 예시";
const disabled = ["비활성 · 입력 유지", "접근성 비활성"];

function paint(button) {
  return button.evaluate(async element => {
    const css = getComputedStyle(element);
    // Force style resolution before waiting for possible CSS transitions.
    void css.backgroundColor;
    await Promise.all(element.getAnimations().map(animation => animation.finished));
    return { background: css.backgroundColor, color: css.color, border: css.borderTopColor, shadow: css.boxShadow };
  });
}

async function checkPage(page, url, canHover) {
  await page.goto(url);
  assert.equal(await page.evaluate(() => matchMedia("(any-hover: hover)").matches), canHover);
  for (const name of [...variants, buttonLink, legacy, selected, ...disabled]) {
    const button = page.getByRole(name === buttonLink ? "link" : "button", {name, exact: true});
    await button.scrollIntoViewIfNeeded();
    await page.mouse.move(0, 0);
    const before = await paint(button);
    await button.hover({force: true});
    const after = await paint(button);
    if (!canHover || disabled.includes(name)) {
      assert.deepEqual(after, before, `${name}: touch or disabled state must retain its paint`);
    } else if (name === legacy) {
      assert.notEqual(after.shadow, before.shadow);
      assert.match(after.shadow, /\binset\b/);
      const alpha = await button.evaluate(element => {
        const shadow = getComputedStyle(element).boxShadow;
        const color = shadow.match(/(?:rgba?|color|oklch|oklab)\([^)]*\)/)?.[0];
        if (!color) return 0;
        const context = document.createElement("canvas").getContext("2d");
        context.fillStyle = color;
        context.fillRect(0, 0, 1, 1);
        return context.getImageData(0, 0, 1, 1).data[3];
      });
      assert.ok(alpha > 0, "legacy hover tint is visible, not transparent");
    } else {
      assert.ok(after.background !== before.background || after.border !== before.border || after.color !== before.color,
        `${name}: hover must change the background, border or text color`);
    }
    if (name === selected) {
      assert.equal(await button.getAttribute("aria-current"), "page");
      assert.notEqual(before.shadow, "none", "selected row has a persistent marker");
      assert.ok(after.shadow.includes(before.shadow), "selected marker survives hover");
    }
    await page.mouse.move(0, 0);
    assert.deepEqual(await paint(button), before, `${name}: pointer exit restores its original appearance`);
  }
}

async function checkLightDisabledContrast(page) {
  await page.evaluate(() => { document.documentElement.dataset.theme = "light"; });
  for (const name of disabled) {
    const ratio = await page.getByRole("button", {name, exact: true}).evaluate(button => {
      const channels = color => color.match(/[\d.]+/g).map(Number);
      const over = (rgb, backdrop, alpha) => rgb.slice(0, 3).map((v, i) => v * alpha + backdrop[i] * (1 - alpha));
      const luminance = rgb => rgb.reduce((sum, value, i) => {
        const s = value / 255;
        return sum + [0.2126, 0.7152, 0.0722][i] * (s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4);
      }, 0);
      const css = getComputedStyle(button);
      const opacity = Number(css.opacity);
      const white = [255, 255, 255];
      const background = channels(css.backgroundColor);
      const fill = over(background, white, background[3] ?? 1);
      const color = channels(css.color);
      const fg = luminance(over(over(color, fill, color[3] ?? 1), white, opacity));
      const bg = luminance(over(fill, white, opacity));
      return (Math.max(fg, bg) + 0.05) / (Math.min(fg, bg) + 0.05);
    });
    assert.ok(ratio >= 4.5, `${name}: disabled label on the light surface has contrast ${ratio.toFixed(2)}`);
  }
}

const server = await createPreviewServer();
let browser;
try {
  await server.listen();
  const url = `http://127.0.0.1:${server.httpServer.address().port}/__design_system__/?frame=1&section=common`;
  browser = await chromium.launch({channel: process.env.UI_STYLE_BROWSER ?? "msedge", headless: true});
  for (const canHover of [true, false]) {
    const page = await browser.newPage({viewport: {width: 1280, height: 900}, isMobile: !canHover, hasTouch: !canHover});
    await checkPage(page, url, canHover);
    await checkLightDisabledContrast(page);
    await page.close();
    console.log(`${canHover ? "Mouse" : "Touch"}: passed shared, native, selected, and disabled button checks.`);
  }
} finally {
  try { await browser?.close(); } finally { await server.close(); }
}
