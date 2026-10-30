import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "../..");
const require = createRequire(resolve(frontend, "package.json"));
const vitestRequire = createRequire(require.resolve("vitest/package.json"));
const { createServer } = await import(pathToFileURL(vitestRequire.resolve("vite")).href);
const playwrightRequire = createRequire(require.resolve("@playwright/test/package.json"));
const { chromium } = playwrightRequire("playwright");
const { expect } = require("@playwright/test");
const output = resolve(frontend, process.env.UI_STYLE_OUTPUT_DIR ?? "../.local-data/browser-verification/agents-20261023");
await mkdir(output, { recursive: true });
const serveOnly = process.argv.includes("--serve-only");
const report = { synthetic: true, authenticated: false, modelCalls: 0, apiCalls: 0, viewports: [], errors: [] };
let browser;
async function openSyntheticPage(context) {
  let timer;
  try {
    return await Promise.race([
      context.newPage(),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Installed browser did not create the blank synthetic page within 30 seconds.")), 30_000); }),
    ]);
  } finally { clearTimeout(timer); }
}
console.log("Preparing the synthetic UI server.");
const server = await createServer({
  root: frontend, configFile: false, logLevel: "error",
  resolve: { alias: [{ find: /^next\/link$/, replacement: resolve(here, "link.fixture.tsx") }] },
  oxc: { jsx: { runtime: "automatic" } },
  server: { host: "127.0.0.1", port: 0, strictPort: false },
  plugins: [{ name: "agent-trace-synthetic-entry", configureServer(instance) {
    instance.middlewares.use(async (req, res, next) => {
      if (req.url !== "/__agent_trace__/") return next();
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.end(await instance.transformIndexHtml(req.url, '<!doctype html><html lang="ko"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="root"></div><script type="module" src="/tests/ui-style/agent-trace.fixture.tsx"></script></body></html>'));
    });
  } }],
});

try {
  await server.listen();
  const origin = `http://127.0.0.1:${server.httpServer.address().port}`;
  if (serveOnly) {
    console.log(JSON.stringify({ synthetic: true, authenticated: false, serveOnly: true,
      url: `${origin}/__agent_trace__/`, message: "Synthetic components and CSS only. Stop this process after browser verification." }));
    await new Promise(resolve => {
      process.once("SIGINT", resolve);
      process.once("SIGTERM", resolve);
    });
  } else {
  console.log("Synthetic UI server is listening; starting the installed browser.");
  browser = await chromium.launch({ channel: process.env.UI_STYLE_BROWSER ?? "msedge", headless: true, chromiumSandbox: true });
  console.log("Checking the real component and CSS at 1280, 375 and 320px.");
  const context = await browser.newContext();
  console.log("Blank browser context created.");
  await context.route("**/*", route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin || url.pathname.startsWith("/api/")) {
      report.errors.push(`Blocked request ${url.origin}${url.pathname}`);
      return route.abort();
    }
    return route.continue();
  });
  const page = await openSyntheticPage(context);
  console.log("Synthetic page created.");
  page.setDefaultTimeout(15_000);
  page.on("pageerror", error => report.errors.push(error.message));
  for (const width of [1280, 375, 320]) {
    await page.setViewportSize({ width, height: 960 });
    await page.goto(`${origin}/__agent_trace__/`);
    console.log(`Loaded synthetic fixture at ${width}px.`);
    await page.getByText(/검색 근거·유사도/, { exact: false }).click();
    const panel = page.getByRole("region", { name: "에이전트 위임 흐름" });
    const diagram = panel.getByRole("region", { name: "에이전트 위임 그림" });
    const nodes = panel.getByRole("list", { name: "에이전트 실행과 위임 단계" });
    const selected = panel.getByRole("region", { name: "선택한 단계 상세" });
    const root = diagram.getByRole("button", { name: /에이전트.*synthetic_manager/ });
    const delegation = diagram.getByRole("button", { name: /위임.*synthetic_delegate/ });
    await root.focus();
    await page.keyboard.press("Tab");
    await expect(delegation).toBeFocused();
    const focus = await delegation.evaluate(element => {
      const style = getComputedStyle(element);
      return { visible: element.matches(":focus-visible"), width: parseFloat(style.outlineWidth), style: style.outlineStyle };
    });
    assert.ok(focus.visible && focus.width >= 2 && focus.style !== "none", "Keyboard focus must be visible");
    await page.keyboard.press("Space");
    await expect(delegation).toHaveAttribute("aria-pressed", "true");
    await expect(selected.getByText("결과를 돌려받는 도구 위임 (as_tool)")).toBeVisible();
    await page.keyboard.press("Tab");
    await page.keyboard.press("Enter");
    await expect(selected.getByRole("heading", { name: "에이전트 · synthetic_writer" })).toBeVisible();
    await page.keyboard.press("Escape");
    const flowGeometry = await diagram.evaluate(element => {
      const cards = [...element.querySelectorAll('button[aria-label^="에이전트 ·"]')].map(button => button.getBoundingClientRect());
      return { horizontal: cards[1].left >= cards[0].right, vertical: cards[1].top >= cards[0].bottom };
    });
    assert.ok(width === 1280 ? flowGeometry.horizontal : flowGeometry.vertical, "Agent cards and arrows must respond to available width");
    await panel.getByText("전체 단계 기록 (5)", { exact: true }).click();
    await nodes.getByRole("button", { name: /모델 호출.*synthetic_generation/ }).click();
    await selected.getByText("전달 입력", { exact: true }).click();
    await expect(selected.locator('pre[aria-label="전달 입력"]')).toContainText("합성 질문과 조건을 그대로 전달합니다");
    const geometry = await panel.evaluate(element => {
      const nodes = element.querySelector('ol[aria-label="에이전트 실행과 위임 단계"]');
      const detail = element.querySelector('[aria-label="선택한 단계 상세"]');
      const nodeBox = nodes.getBoundingClientRect();
      const detailBox = detail.getBoundingClientRect();
      return { width: innerWidth, overflow: document.documentElement.scrollWidth > innerWidth,
        panelWidth: element.getBoundingClientRect().width,
        stacked: detailBox.top > nodeBox.bottom,
        buttons: [...nodes.querySelectorAll("button")].map(button => ({
          height: button.getBoundingClientRect().height, inside: button.getBoundingClientRect().right <= innerWidth,
        })),
        inputOverflow: detail.querySelector("pre").scrollWidth > detail.querySelector("pre").clientWidth,
      };
    });
    assert.equal(geometry.overflow, false, "The page must not overflow horizontally");
    assert.equal(geometry.inputOverflow, false, "Long input must wrap inside the detail");
    assert.ok(geometry.buttons.every(button => button.height >= 44 && button.inside), "All stage targets must fit and be at least 44px high");
    assert.ok(geometry.stacked, "Selected detail must follow the complete records");
    await panel.screenshot({ path: resolve(output, `current-${width}.png`) });
    await page.getByRole("button", { name: "합성 실행 이력" }).click();
    await diagram.getByRole("button", { name: /위임.*synthetic_delegate/ }).click();
    await selected.getByText("전달 입력", { exact: true }).click();
    await expect(selected.locator("details[open]").getByText(/본문 미보관/)).toBeVisible();
    await expect(selected.locator("pre")).toHaveCount(0);
    await panel.screenshot({ path: resolve(output, `history-${width}.png`) });
    await page.getByRole("button", { name: "합성 관측 누락" }).click();
    await diagram.getByRole("button", { name: /에이전트.*synthetic_manager/ }).click();
    await expect(panel.getByText(/일부 관측 기록이 누락/)).toBeVisible();
    await expect(panel.getByText(/일부 단계가 생략/)).toBeVisible();
    await expect(selected.getByRole("alert")).toContainText("agent_model_call_limit");
    await page.getByRole("button", { name: "합성 이전 기록" }).click();
    await expect(panel.getByText(/위임 기록이 없는 실행/)).toBeVisible();
    await expect(panel.getByRole("button")).toHaveCount(0);
    report.viewports.push({ ...geometry, flowGeometry, focus, keyboardSelection: true, historyWithoutBody: true, partialAndEmpty: true });
  }
  await page.setViewportSize({ width: 1280, height: 960 });
  await page.getByRole("button", { name: "합성 실행 이력" }).click();
  await page.getByRole("button", { name: "좁은 컨테이너" }).click();
  const narrowPanel = page.getByRole("region", { name: "에이전트 위임 흐름" });
  const narrow = await narrowPanel.evaluate(element => {
    const diagram = element.querySelector('[aria-label="에이전트 위임 그림"]');
    const cards = [...diagram.querySelectorAll('button[aria-label^="에이전트 ·"]')].map(button => button.getBoundingClientRect());
    return { width: element.getBoundingClientRect().width, stacked: cards[1].top >= cards[0].bottom };
  });
  assert.ok(narrow.width <= 560 && narrow.stacked, "A narrow container must stack even on desktop");
  report.narrowContainer = narrow;
  await narrowPanel.screenshot({ path: resolve(output, "narrow-container.png") });
  assert.deepEqual(report.errors, []);
  console.log(JSON.stringify({ ok: true, output, viewports: report.viewports.length, narrowContainer: true }));
  }
} catch (error) {
  report.errors.push(error.stack ?? String(error));
  console.error(error.stack ?? String(error));
  throw error;
} finally {
  if (!serveOnly) {
    await writeFile(resolve(output, "report.json"), JSON.stringify(report, null, 2));
    console.log(`Saved synthetic verification report: ${output}`);
  }
  await browser?.close();
  await server.close();
}
