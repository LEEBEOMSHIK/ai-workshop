import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "../..");
const require = createRequire(resolve(frontend, "package.json"));
// Use already installed transitive tooling; this command never installs packages.
const vitestRequire = createRequire(require.resolve("vitest/package.json"));
const { createServer } = await import(pathToFileURL(vitestRequire.resolve("vite")).href);
const playwrightRequire = createRequire(require.resolve("@playwright/test/package.json"));
const { chromium } = playwrightRequire("playwright");
const { expect } = require("@playwright/test");
const output = resolve(frontend, process.env.UI_STYLE_OUTPUT_DIR ?? "../.local-data/browser-verification/preparation");
await mkdir(output, { recursive: true });
const baseline = process.argv.includes("--baseline");
const report = { synthetic: true, authenticated: false, requests: [], viewports: [], errors: [] };
let browser;
const server = await createServer({
  root: frontend, configFile: false, logLevel: "error",
  resolve: { alias: [{ find: /^next\/link$/, replacement: resolve(here, "link.fixture.tsx") }] },
  oxc: { jsx: { runtime: "automatic" } },
  server: { host: "127.0.0.1", port: 0, strictPort: false },
  plugins: [{ name: "synthetic-ui-entry", configureServer(instance) {
    instance.middlewares.use(async (req, res, next) => {
      if (req.url !== "/__ui_style__/") return next();
      res.setHeader("Content-Type", "text/html; charset=utf-8");
      res.end(await instance.transformIndexHtml(req.url, '<!doctype html><html lang="ko"><head><meta name="viewport" content="width=device-width,initial-scale=1"></head><body><div id="root"></div><script type="module" src="/tests/ui-style/preparation.fixture.tsx"></script></body></html>'));
    });
  } }],
});
try {
  await server.listen();
  const address = server.httpServer.address();
  const origin = `http://127.0.0.1:${address.port}`;
  browser = await chromium.launch({ channel: process.env.UI_STYLE_BROWSER ?? "msedge", headless: true, chromiumSandbox: true });
  const context = await browser.newContext();
  await context.route("**/*", async route => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin) { report.errors.push(`Blocked external request: ${url.origin}`); return route.abort(); }
    if (!url.pathname.startsWith("/api/")) return route.continue();
    const body = request.method() === "POST" ? request.postDataJSON() : undefined;
    report.requests.push({ path: url.pathname, method: request.method(), ...(body ? { body } : {}) });
    // Every API, including synthetic submissions, is fulfilled here; nothing reaches a backend.
    const base = "/api/v1/rag/evaluation-authoring";
    const item = { document_id: "document", workspace_id: "workspace", asset_version_id: "asset", title: "Synthetic document", number: 1, ready: true, sha256: "hash" };
    const syntheticCase = { id: "synthetic-case", query: "합성 경계 질문", expected_answer_status: "insufficient_evidence", expected_evidence_ids: [], expected_highlight: null };
    if (request.method() === "GET" && url.pathname === "/api/v1/rag/generative-evaluations/policies") {
      return route.fulfill({ json: [{ id: "policy", name: "Synthetic policy", definition: { version: 1 } }] });
    }
    if (request.method() === "GET" && url.pathname === "/api/v1/rag/generative-evaluations") return route.fulfill({ json: [] });
    if (request.method() === "GET" && url.pathname === `${base}/snapshots/synthetic-data`) {
      return route.fulfill({ json: { id: "synthetic-data", cases: [syntheticCase] } });
    }
    if (request.method() === "POST" && url.pathname === `${base}/documents`) return route.fulfill({ json: { documents: [item], next_cursor: null } });
    if (request.method() === "POST" && url.pathname === `${base}/preview`) return route.fulfill({ json: {
      complete: true, scope: { configuration_version_id: "candidate", workspace_ids: ["workspace"], asset_version_ids: ["asset"] },
      scope_sha256: "synthetic-hash", documents: [item], evidence: [], document_count: 1, evidence_count: 0 } });
    if (request.method() === "POST" && url.pathname === `${base}/snapshots`) return route.fulfill({ json: {
      id: "synthetic-created", cases: [{ ...syntheticCase, id: "created-case", query: "합성 새 질문" }] } });
    if (request.method() === "POST" && url.pathname === "/api/v1/rag/generative-evaluations") return route.fulfill({ json: {
      id: "synthetic-run", created_at: "2026-10-19T00:00:00Z", status: "pending", repetition_count: 2, attempts: [] } });
    report.errors.push(`Blocked unexpected API: ${request.method()} ${url.pathname}`);
    return route.abort();
  });
  const page = await context.newPage();
  page.setDefaultTimeout(15_000);
  page.on("pageerror", error => report.errors.push(error.message));
  for (const width of [1280, 375, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`${origin}/__ui_style__/`);
    await page.getByText("새 생성형 평가 준비", { exact: true }).click();
    const group = page.getByRole("group", { name: "평가 자료 준비 방식" });
    await group.waitFor();
    const geometry = await group.evaluate(element => {
      const radios = [...element.querySelectorAll('input[type="radio"]')].map(input => {
        const label = input.closest("label");
        const walker = document.createTreeWalker(label, NodeFilter.SHOW_TEXT);
        let text;
        while (walker.nextNode()) if (walker.currentNode.textContent.trim()) { text = walker.currentNode; break; }
        const range = document.createRange(); range.selectNodeContents(text);
        const textBox = range.getBoundingClientRect();
        const box = input.getBoundingClientRect();
        const labelBox = label.getBoundingClientRect();
        const inputStyle = getComputedStyle(input);
        return { width: box.width, height: box.height, labelHeight: labelBox.height,
          sameRow: Math.abs(box.y + box.height / 2 - textBox.y - textBox.height / 2) < 6,
          inputBeforeText: box.right <= textBox.left, labelDisplay: getComputedStyle(label).display,
          visuallyHidden: inputStyle.position === "absolute" && (inputStyle.clipPath !== "none" || inputStyle.clip !== "auto" || inputStyle.opacity === "0"),
          accessible: inputStyle.display !== "none" && inputStyle.visibility !== "hidden" && !input.hasAttribute("aria-hidden"),
          label: { x: labelBox.x, y: labelBox.y, width: labelBox.width, right: labelBox.right } };
      });
      return { width: innerWidth, groupHeight: element.getBoundingClientRect().height,
        overflow: document.documentElement.scrollWidth > innerWidth, radios };
    });
    report.viewports.push(geometry);
    await page.screenshot({ path: resolve(output, `${baseline ? "before" : "after"}-${width}.png`), fullPage: true });
    await group.screenshot({ path: resolve(output, `${baseline ? "before" : "after"}-choice-${width}.png`) });
    if (baseline) continue;

    const saved = group.getByRole("radio", { name: "저장 자료 재사용" });
    const create = group.getByRole("radio", { name: "새 자료 작성" });
    await page.getByText("새 생성형 평가 준비", { exact: true }).focus();
    await page.keyboard.press("Tab");
    await expect(saved).toBeFocused();
    const focus = await saved.evaluate(element => ({ visible: element.matches(":focus-visible"),
      width: getComputedStyle(element.closest("label")).outlineWidth, style: getComputedStyle(element.closest("label")).outlineStyle,
      color: getComputedStyle(element.closest("label")).outlineColor }));
    assert.ok(focus.visible && parseFloat(focus.width) >= 2 && focus.style !== "none", "Keyboard focus must remain visible");
    await group.screenshot({ path: resolve(output, `after-focus-${width}.png`) });
    await page.keyboard.press("ArrowRight");
    await expect(create).toBeChecked();
    await expect(page.getByLabel("저장된 평가 자료 ID")).toHaveCount(0);
    await page.keyboard.press("ArrowLeft");
    await expect(saved).toBeChecked();
    await create.focus(); await page.keyboard.press("Space");
    await expect(create).toBeChecked();
    await saved.locator("..").click();
    await expect(saved).toBeChecked();
    await page.getByLabel("저장된 평가 자료 ID").fill("synthetic-data");
    await page.getByRole("button", { name: "평가 자료 불러오기" }).click();
    const rule = page.getByLabel("반드시 포함할 내용 (한 줄에 하나)");
    await rule.fill("합성 보존 규칙");
    await create.locator("..").click();
    await saved.locator("..").click();
    await expect(rule).toHaveValue("합성 보존 규칙");

    const visualState = locator => locator.evaluate(input => {
      const style = getComputedStyle(input.closest("label"));
      return { background: style.backgroundColor, color: style.color, weight: style.fontWeight,
        decoration: style.textDecorationLine };
    });
    const selected = await visualState(saved);
    const idle = await visualState(create);
    assert.notEqual(selected.background, idle.background, "Selection must have a distinct surface");
    assert.ok(selected.decoration.includes("underline"), "Selection must have a non-color cue");
    await create.locator("..").hover();
    const hover = await visualState(create);
    assert.notEqual(hover.background, idle.background, "Enabled segment hover must be visible");
    await page.mouse.move(0, 0);

    // Exercise both submissions in the actual CSS browser using intercepted synthetic APIs only.
    await page.getByRole("checkbox", { name: "Synthetic candidate v1" }).check();
    await page.getByLabel("생성형 승격 기준").selectOption("policy");
    await page.getByLabel("이전 질문 문맥 (선택, 원문 그대로 고정)").fill("저장 모드 합성 문맥");
    await create.locator("..").click();
    await page.getByRole("checkbox", { name: "Synthetic workspace" }).check();
    await page.getByRole("button", { name: "문서 목록 불러오기" }).click();
    await page.getByRole("checkbox", { name: "Synthetic document v1" }).check();
    await page.getByRole("button", { name: "근거 불러오기" }).click();
    await page.getByRole("textbox", { name: "질문 1", exact: true }).fill("합성 새 질문");
    await page.getByLabel("기대 결과 1").selectOption("insufficient_evidence");
    await page.getByLabel("평가 이름").fill("합성 보존 초안");
    await page.getByRole("checkbox", { name: "자료와 질문의 불변 보관을 확인합니다" }).check();
    await page.getByRole("button", { name: "평가 자료 저장" }).click();
    await expect(page.locator("legend").filter({ hasText: /^합성 새 질문$/ })).toBeVisible();
    await rule.fill("새 모드 합성 규칙");
    await page.getByLabel("이전 질문 문맥 (선택, 원문 그대로 고정)").fill("새 모드 합성 문맥");
    await saved.locator("..").click();
    await expect(rule).toHaveValue("합성 보존 규칙");
    const submissions = () => report.requests.filter(item => item.method === "POST" && item.path === "/api/v1/rag/generative-evaluations");
    const count = submissions().length;
    await page.getByRole("button", { name: "생성형 평가 실행", exact: true }).click();
    await expect.poll(() => submissions().length).toBe(count + 1);
    const savedBody = submissions().at(-1).body;
    assert.equal(savedBody.dataset_snapshot_id, "synthetic-data");
    assert.deepEqual(savedBody.expected_rules["synthetic-case"].required_propositions, ["합성 보존 규칙"]);
    assert.equal(savedBody.case_histories["synthetic-case"][0].content, "저장 모드 합성 문맥");
    assert.ok(!JSON.stringify(savedBody).includes("새 모드 합성"));
    await expect(page.getByRole("button", { name: "생성형 평가 실행", exact: true })).toBeEnabled();
    await create.locator("..").click();
    await expect(page.getByLabel("평가 이름")).toHaveValue("합성 보존 초안");
    await expect(page.getByRole("textbox", { name: "질문 1", exact: true })).toHaveValue("합성 새 질문");
    await expect(rule).toHaveValue("새 모드 합성 규칙");
    await page.getByRole("button", { name: "생성형 평가 실행", exact: true }).click();
    await expect.poll(() => submissions().length).toBe(count + 2);
    const createdBody = submissions().at(-1).body;
    assert.equal(createdBody.dataset_snapshot_id, "synthetic-created");
    assert.deepEqual(createdBody.expected_rules["created-case"].required_propositions, ["새 모드 합성 규칙"]);
    assert.equal(createdBody.case_histories["created-case"][0].content, "새 모드 합성 문맥");
    assert.ok(!JSON.stringify(createdBody).includes("합성 보존 규칙"));
    await expect(page.getByRole("button", { name: "생성형 평가 실행", exact: true })).toBeEnabled();
    await saved.locator("..").click();
    geometry.syntheticSubmissions = { saved: true, create: true, isolatedRulesAndHistory: true, retainedDraft: true };
    geometry.states = { selected, idle, hover };

    const narrow = page.getByRole("group", { name: "좁은 영역의 긴 선택 문구" });
    const narrowRadios = narrow.getByRole("radio");
    await narrowRadios.first().focus(); await page.keyboard.press("ArrowRight");
    await expect(narrowRadios.last()).toBeChecked();
    await expect(narrow.getByRole("radio", { name: "선택 불가" })).toBeDisabled();
    await expect(saved).toBeChecked();
    const disabled = page.getByRole("group", { name: "비활성 그룹" });
    await expect(disabled.getByRole("radio", { name: "보존된 선택" })).toBeChecked();
    for (const input of await disabled.getByRole("radio").all()) await expect(input).toBeDisabled();
    const disabledInput = disabled.getByRole("radio").last();
    const disabledIdle = await visualState(disabledInput);
    await disabledInput.locator("..").hover();
    assert.deepEqual(await visualState(disabledInput), disabledIdle, "Disabled segments must not gain hover state");
    const ordinary = page.getByRole("group", { name: "기본 원형 선택" });
    const ordinaryRadios = ordinary.getByRole("radio");
    const glyph = await ordinaryRadios.first().boundingBox();
    assert.equal(glyph.width, 16); assert.equal(glyph.height, 16);
    await ordinaryRadios.first().focus(); await page.keyboard.press("ArrowRight");
    await expect(ordinaryRadios.last()).toBeChecked();
    await expect(saved).toBeChecked();
    geometry.defaultVariant = { glyph: 16, keyboard: true, isolated: true };
    const boundary = await narrow.evaluate(element => {
      const box = element.getBoundingClientRect();
      return { width: box.width, overflow: element.scrollWidth > element.clientWidth + 1,
        labelsFit: [...element.querySelectorAll("label")].every(label => label.getBoundingClientRect().right <= box.right + 1) };
    });
    assert.ok(!boundary.overflow && boundary.labelsFit && boundary.width <= 240, "Long labels must fit a narrow container");
    await narrow.screenshot({ path: resolve(output, `after-narrow-${width}.png`) });
    geometry.keyboard = { tab: true, arrows: true, space: true, labelClick: true, disabledSkip: true, isolatedGroups: true, retainedInput: true, focus };
    geometry.narrow = boundary;
  }
  assert.deepEqual(report.errors, []);
  for (const viewport of report.viewports) {
    assert.equal(viewport.overflow, false, `Overflow at ${viewport.width}px`);
    for (const radio of viewport.radios) {
      assert.ok(radio.visuallyHidden && radio.accessible && radio.width <= 2 && radio.height <= 2, `Segment must hide only the radio glyph: ${JSON.stringify(radio)}`);
      assert.ok(radio.labelHeight >= 44, "Label hit area must be at least 44px");
    }
    const [first, second] = viewport.radios;
    assert.ok(Math.abs(first.label.y - second.label.y) <= 1 && Math.abs(first.label.right - second.label.x) <= 1, "Mode segments must be connected in one row");
  }
  report.passed = true;
} finally {
  await writeFile(resolve(output, `${baseline ? "before" : "after"}-report.json`), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report));
  await browser?.close();
  await server.close();
}
