import { expect, test, type APIResponse, type Page } from "@playwright/test";
import { spawn, type ChildProcessWithoutNullStreams } from "node:child_process";
import { writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { createInterface } from "node:readline";

interface StudyContent {
  slug: string;
  title: string;
  summary: string;
  topic_keys: string[];
  body: string;
  verification: string;
  limitations: string;
  persona: null;
}

interface StudySnapshot {
  schema_version: 1;
  revision: number;
  content: StudyContent;
}

interface StudyAdminView {
  snapshot: StudySnapshot;
  digest: string;
  applied_action: "publish" | "withdraw" | null;
  applied_revision: number | null;
  delivery_pending: boolean;
  pending_command: {
    action: "publish" | "withdraw";
    expected_revision: number;
    expected_digest: string;
    request_id: string;
  } | null;
}

const environment = {
  baseURL: requiredEnvironment("PUBLISHING_TEST_BASE_URL"),
  publicOnlyBaseURL: requiredEnvironment("PUBLISHING_TEST_PUBLIC_ONLY_BASE_URL"),
  privateOrigin: requiredEnvironment("PUBLISHING_TEST_PRIVATE_ORIGIN"),
  publicOrigin: requiredEnvironment("PUBLISHING_TEST_PUBLIC_ORIGIN"),
  email: requiredEnvironment("PUBLISHING_TEST_EMAIL"),
  password: requiredEnvironment("PUBLISHING_TEST_PASSWORD"),
  slug: requiredSlug("PUBLISHING_TEST_SLUG"),
  store: requiredEnvironment("PUBLISHING_TEST_PUBLIC_STORE"),
  python: requiredEnvironment("PUBLISHING_TEST_PYTHON"),
};

const hostileMarker = `publishing-e2e-probe-${environment.slug}`;
const initialContent: StudyContent = {
  slug: environment.slug,
  title: `합성 공개 연구 ${environment.slug}`,
  summary: `합성 요약 <strong>${hostileMarker}</strong>`,
  topic_keys: ["retrieval", "evidence"],
  body: [
    "합성 본문이며 실제 비공개 원문을 포함하지 않습니다.",
    `<script>window.${hostileMarker.replaceAll("-", "_")} = true</script>`,
    `<img src="http://127.0.0.1:9/${hostileMarker}.png" alt="must-not-load">`,
  ].join("\n"),
  verification: "합성 브라우저 인수 검증: 생성·편집·미리보기·공개·철회.",
  limitations: "합성 데이터이며 운영 데이터와 분리된 환경에서만 유효합니다.",
  persona: null,
};
const revisionTwoContent: StudyContent = {
  ...initialContent,
  title: `${initialContent.title} · 편집본`,
  body: `${initialContent.body}\nUI 편집 리비전 2`,
};
const revisionTwoSnapshot: StudySnapshot = {
  schema_version: 1,
  revision: 2,
  content: revisionTwoContent,
};
const revisionThreeContent: StudyContent = {
  ...initialContent,
  title: `${initialContent.title} · 로컬 편집 3`,
  body: `${initialContent.body}\nUI 편집 리비전 3`,
};

test("real Publishing lifecycle preserves revisions, escapes text, recovers delivery, and updates public links", async ({ browser }, testInfo) => {
  const httpEvidence: Array<Record<string, unknown>> = [];
  const anonymousContext = await browser.newContext({ baseURL: environment.baseURL });
  const ownerContext = await browser.newContext({ baseURL: environment.baseURL });
  const anonymousPage = await anonymousContext.newPage();
  const ownerPage = await ownerContext.newPage();
  const anonymousErrors = observeErrors(anonymousPage);
  const ownerErrors = observeErrors(ownerPage);
  const hostileRequests: string[] = [];
  anonymousPage.on("request", (request) => {
    if (request.url().includes(hostileMarker)) hostileRequests.push(request.url());
  });

  try {
    await test.step("anonymous public access works while admin redirects to login", async () => {
      const directPublic = await anonymousContext.request.get(`${environment.publicOrigin}/api/public/studies`);
      recordResponse(httpEvidence, "initial-public-list", directPublic);
      expect(directPublic.status()).toBe(200);
      expect(((await directPublic.json()) as { items: StudySnapshot[] }).items.some((item) => item.content.slug === environment.slug)).toBe(false);

      await anonymousPage.goto("/labs/rag/studies");
      await expect(anonymousPage.getByRole("heading", { name: "공개 연구 기록" })).toBeVisible();
      await anonymousPage.goto("/admin/publishing");
      await expect(anonymousPage).toHaveURL(/\/login\?next=%2Fadmin%2Fpublishing$/);
      await expect(anonymousPage.getByRole("heading", { name: "다시 오셨군요." })).toBeVisible();
    });

    await test.step("owner signs in through the real login UI", async () => {
      await ownerPage.goto("/login?next=%2Fadmin%2Fpublishing");
      await ownerPage.getByLabel("이메일").fill(environment.email);
      await ownerPage.getByLabel("비밀번호").fill(environment.password);
      await ownerPage.getByRole("button", { name: "작업소 입장" }).click();
      await expect(ownerPage).toHaveURL(/\/admin\/publishing$/);
      await expect(ownerPage.getByRole("heading", { name: "공개 연구 관리" })).toBeVisible();

      const proxiedIdentity = await ownerContext.request.get(`${environment.baseURL}/api/v1/auth/me`);
      const declaredPrivateIdentity = await ownerContext.request.get(`${environment.privateOrigin}/api/v1/auth/me`);
      recordResponse(httpEvidence, "proxied-owner-identity", proxiedIdentity);
      recordResponse(httpEvidence, "declared-private-owner-identity", declaredPrivateIdentity);
      expect(proxiedIdentity.status()).toBe(200);
      expect(declaredPrivateIdentity.status()).toBe(200);
      expect(await declaredPrivateIdentity.json()).toEqual(await proxiedIdentity.json());
    });

    await test.step("wide keyboard path creates a private draft and edits it", async () => {
      await ownerPage.setViewportSize({ width: 1440, height: 900 });
      await expectNoHorizontalOverflow(ownerPage);
      const create = ownerPage.getByRole("button", { name: "새 기록" });
      await create.focus();
      await ownerPage.keyboard.press("Enter");
      await fillStudyForm(ownerPage, initialContent);
      const createResponsePromise = ownerPage.waitForResponse((response) => response.url().endsWith("/api/v1/admin/publishing/studies") && response.request().method() === "POST");
      await ownerPage.getByRole("button", { name: "비공개 기록 만들기" }).click();
      const createResponse = await createResponsePromise;
      recordResponse(httpEvidence, "create-private", createResponse);
      expect(createResponse.status()).toBe(201);
      const created = (await createResponse.json()) as StudyAdminView;
      expect(created.snapshot).toEqual({ schema_version: 1, revision: 1, content: initialContent });
      expect(created.applied_action).toBeNull();
      const declaredPrivateCreated = await ownerContext.request.get(
        `${environment.privateOrigin}/api/v1/admin/publishing/studies/${environment.slug}`,
      );
      recordResponse(httpEvidence, "declared-private-created-detail", declaredPrivateCreated);
      expect(declaredPrivateCreated.status()).toBe(200);
      expect(((await declaredPrivateCreated.json()) as StudyAdminView).snapshot).toEqual(created.snapshot);
      await expect(ownerPage.getByLabel("공개 주소 슬러그")).toBeDisabled();

      await ownerPage.getByLabel("제목").fill(revisionTwoContent.title);
      await ownerPage.getByLabel("본문").fill(revisionTwoContent.body);
      const updateResponsePromise = ownerPage.waitForResponse((response) => response.url().endsWith(`/api/v1/admin/publishing/studies/${environment.slug}`) && response.request().method() === "PUT");
      await ownerPage.getByRole("button", { name: "변경 저장" }).click();
      const updateResponse = await updateResponsePromise;
      recordResponse(httpEvidence, "ui-edit-revision-2", updateResponse);
      expect(updateResponse.status()).toBe(200);
      expect(((await updateResponse.json()) as StudyAdminView).snapshot).toEqual(revisionTwoSnapshot);
      await ownerPage.screenshot({ path: testInfo.outputPath("01-admin-wide.png"), fullPage: true });
    });

    await test.step("exact server preview is explicitly published", async () => {
      const previewResponsePromise = ownerPage.waitForResponse((response) => response.url().endsWith(`/api/v1/admin/publishing/studies/${environment.slug}/preview`));
      await ownerPage.getByRole("button", { name: "서버 미리보기" }).click();
      const previewResponse = await previewResponsePromise;
      recordResponse(httpEvidence, "preview-revision-2", previewResponse);
      expect(previewResponse.status()).toBe(200);
      const preview = (await previewResponse.json()) as { snapshot: StudySnapshot; digest: string };
      expect(preview.snapshot).toEqual(revisionTwoSnapshot);
      const previewRegion = ownerPage.getByRole("region", { name: "서버 미리보기" });
      await expect(previewRegion).toContainText(revisionTwoContent.title);
      await expect(previewRegion).toContainText(revisionTwoContent.summary);
      await expect(previewRegion).toContainText(revisionTwoContent.body);
      await expect(previewRegion).toContainText(revisionTwoContent.verification);
      await expect(previewRegion).toContainText(revisionTwoContent.limitations);
      const previewTopics = previewRegion.locator('[aria-label="기술 주제"]');
      await expect(previewTopics).toContainText("retrieval");
      await expect(previewTopics).toContainText("evidence");
      await expect(previewRegion.getByText(/^안내:/u)).toHaveCount(0);
      await expect(previewRegion.locator("script, img")).toHaveCount(0);

      const publishResponsePromise = ownerPage.waitForResponse((response) => response.url().endsWith(`/api/v1/admin/publishing/studies/${environment.slug}/publish`));
      await ownerPage.getByRole("button", { name: "미리보기와 같은 버전 공개" }).click();
      const publishResponse = await publishResponsePromise;
      recordResponse(httpEvidence, "publish-revision-2", publishResponse);
      expect(publishResponse.status()).toBe(200);
      const published = (await publishResponse.json()) as StudyAdminView;
      expect(published.applied_action).toBe("publish");
      expect(published.applied_revision).toBe(2);
      expect(published.delivery_pending).toBe(false);
      await expect(ownerPage.getByRole("region", { name: "공개 적용 상태" })).toContainText("공개본 리비전 2");
    });

    await test.step("anonymous list, detail, chief, and retrieval worker expose only escaped public content", async () => {
      const directDetail = await anonymousContext.request.get(`${environment.publicOrigin}/api/public/studies/${environment.slug}`);
      recordResponse(httpEvidence, "public-detail-revision-2", directDetail);
      expect(directDetail.status()).toBe(200);
      expect((await directDetail.json()) as StudySnapshot).toEqual(revisionTwoSnapshot);

      await anonymousPage.goto("/labs/rag/studies");
      await expect(anonymousPage.getByRole("link", { name: `${initialContent.title} · 편집본 읽기` })).toBeVisible();
      await anonymousPage.getByRole("link", { name: `${initialContent.title} · 편집본 읽기` }).click();
      await expect(anonymousPage.getByRole("heading", { name: `${initialContent.title} · 편집본` })).toBeVisible();
      await expect(anonymousPage.getByText(initialContent.body, { exact: false })).toBeVisible();
      await expect(anonymousPage.locator("article script, article img")).toHaveCount(0);
      expect(await anonymousPage.evaluate((key) => Object.hasOwn(window, key), hostileMarker.replaceAll("-", "_"))).toBe(false);
      expect(hostileRequests).toEqual([]);

      await anonymousPage.goto("/labs/rag");
      await assertNpcStudyLink(
        anonymousPage,
        "RAG 총괄에게 말 걸기",
        `${initialContent.title} · 편집본`,
        testInfo.outputPath("04-npc-related-study.png"),
      );
      await assertNpcStudyLink(anonymousPage, "검색 조율자 리프에게 말 걸기", `${initialContent.title} · 편집본`);
    });

    await test.step("editing a public draft leaves its old public copy unchanged", async () => {
      await ownerPage.getByLabel("제목").fill(revisionThreeContent.title);
      await ownerPage.getByLabel("본문").fill(revisionThreeContent.body);
      const responsePromise = ownerPage.waitForResponse((response) => response.url().endsWith(`/api/v1/admin/publishing/studies/${environment.slug}`) && response.request().method() === "PUT");
      await ownerPage.getByRole("button", { name: "변경 저장" }).click();
      const response = await responsePromise;
      recordResponse(httpEvidence, "ui-edit-revision-3", response);
      expect(response.status()).toBe(200);
      expect(((await response.json()) as StudyAdminView).snapshot).toEqual({
        schema_version: 1,
        revision: 3,
        content: revisionThreeContent,
      });

      const stillPublic = await anonymousContext.request.get(`${environment.publicOrigin}/api/public/studies/${environment.slug}`);
      recordResponse(httpEvidence, "public-copy-after-private-edit", stillPublic);
      expect(stillPublic.status()).toBe(200);
      const snapshot = (await stillPublic.json()) as StudySnapshot;
      expect(snapshot).toEqual(revisionTwoSnapshot);
    });

    await test.step("stale preview returns a real 409 and preserves the visible editor", async () => {
      const previewPromise = ownerPage.waitForResponse((response) => response.url().endsWith(`/api/v1/admin/publishing/studies/${environment.slug}/preview`));
      await ownerPage.getByRole("button", { name: "서버 미리보기" }).click();
      const previewResponse = await previewPromise;
      recordResponse(httpEvidence, "preview-revision-3", previewResponse);
      expect(previewResponse.status()).toBe(200);
      const concurrentContent: StudyContent = {
        ...initialContent,
        title: `${initialContent.title} · 서버 편집 4`,
        body: `${initialContent.body}\n동시 편집 리비전 4`,
      };
      const concurrent = await ownerContext.request.put(
        `${environment.baseURL}/api/v1/admin/publishing/studies/${environment.slug}`,
        {
          headers: publishingMutationHeaders(),
          data: { expected_revision: 3, content: concurrentContent },
        },
      );
      recordResponse(httpEvidence, "concurrent-edit-revision-4", concurrent, "PUT");
      expect(concurrent.status()).toBe(200);
      expect(((await concurrent.json()) as StudyAdminView).snapshot.revision).toBe(4);

      const stalePromise = ownerPage.waitForResponse((response) => response.url().endsWith(`/api/v1/admin/publishing/studies/${environment.slug}/publish`));
      await ownerPage.getByRole("button", { name: "미리보기와 같은 버전 공개" }).click();
      const staleResponse = await stalePromise;
      recordResponse(httpEvidence, "stale-preview-publish", staleResponse);
      expect(staleResponse.status()).toBe(409);
      await expect(ownerPage.getByRole("alert").filter({ hasText: "편집 내용은 보존했습니다" })).toBeVisible();
      await expect(ownerPage.getByLabel("제목")).toHaveValue(revisionThreeContent.title);
      await ownerPage.getByRole("button", { name: "서버 버전 다시 불러오기" }).click();
      await expect(ownerPage.getByLabel("제목")).toHaveValue(concurrentContent.title);

      await ownerPage.getByRole("button", { name: "서버 미리보기" }).click();
      const republishPromise = ownerPage.waitForResponse((response) => response.url().endsWith(`/api/v1/admin/publishing/studies/${environment.slug}/publish`));
      await ownerPage.getByRole("button", { name: "미리보기와 같은 버전 공개" }).click();
      const republish = await republishPromise;
      recordResponse(httpEvidence, "publish-revision-4", republish);
      expect(republish.status()).toBe(200);
      expect(((await republish.json()) as StudyAdminView).applied_revision).toBe(4);
    });

    await test.step("real SQLite lock produces pending withdrawal and exact same-ID retry", async () => {
      let lock: ChildProcessWithoutNullStreams | null = await acquirePublicStoreLock();
      let firstRequest: Record<string, unknown> | null = null;
      let retryRequest: Record<string, unknown> | null = null;
      try {
        const firstResponsePromise = ownerPage.waitForResponse((response) => response.url().endsWith(`/api/v1/admin/publishing/studies/${environment.slug}/withdraw`));
        const firstRequestPromise = ownerPage.waitForRequest((request) => request.url().endsWith(`/api/v1/admin/publishing/studies/${environment.slug}/withdraw`));
        await ownerPage.getByRole("button", { name: "비공개로 전환" }).click();
        firstRequest = (await firstRequestPromise).postDataJSON() as Record<string, unknown>;
        const firstResponse = await firstResponsePromise;
        recordResponse(httpEvidence, "withdraw-delivery-pending", firstResponse);
        expect(firstResponse.status()).toBe(200);
        const pending = (await firstResponse.json()) as StudyAdminView;
        expect(pending.delivery_pending).toBe(true);
        expect(pending.pending_command?.request_id).toBe(firstRequest.request_id);
        await expect(ownerPage.getByRole("status").filter({ hasText: "적용 대기" })).toBeVisible();
        await expect(ownerPage.getByRole("button", { name: "같은 철회 요청 다시 시도" })).toBeVisible();
      } finally {
        if (lock) {
          await releasePublicStoreLock(lock);
          lock = null;
        }
      }

      const retryResponsePromise = ownerPage.waitForResponse((response) => response.url().endsWith(`/api/v1/admin/publishing/studies/${environment.slug}/withdraw`));
      const retryRequestPromise = ownerPage.waitForRequest((request) => request.url().endsWith(`/api/v1/admin/publishing/studies/${environment.slug}/withdraw`));
      await ownerPage.getByRole("button", { name: "같은 철회 요청 다시 시도" }).click();
      retryRequest = (await retryRequestPromise).postDataJSON() as Record<string, unknown>;
      const retryResponse = await retryResponsePromise;
      recordResponse(httpEvidence, "withdraw-same-id-retry", retryResponse);
      expect(retryResponse.status()).toBe(200);
      expect(retryRequest).toEqual(firstRequest);
      const withdrawn = (await retryResponse.json()) as StudyAdminView;
      expect(withdrawn.delivery_pending).toBe(false);
      expect(withdrawn.applied_action).toBe("withdraw");
    });

    await test.step("fresh anonymous routes and NPCs exclude the withdrawn study", async () => {
      const directMissing = await anonymousContext.request.get(`${environment.publicOrigin}/api/public/studies/${environment.slug}`);
      recordResponse(httpEvidence, "withdrawn-direct-detail", directMissing);
      expect(directMissing.status()).toBe(404);

      await anonymousPage.goto("/labs/rag/studies");
      await expect(anonymousPage.getByRole("link", { name: new RegExp(environment.slug) })).toHaveCount(0);
      await anonymousPage.goto(`/studies/${environment.slug}`);
      await expect(anonymousPage.getByRole("heading", { name: "연구 기록을 찾을 수 없습니다" })).toBeVisible();
      await anonymousPage.goto("/labs/rag");
      await assertNpcStudyAbsent(anonymousPage, "RAG 총괄에게 말 걸기", `${initialContent.title} · 서버 편집 4`);
      await assertNpcStudyAbsent(anonymousPage, "검색 조율자 리프에게 말 걸기", `${initialContent.title} · 서버 편집 4`);
    });

    await test.step("narrow desktop remains usable and explicit reapproval republishes", async () => {
      await ownerPage.setViewportSize({ width: 960, height: 720 });
      await expectNoHorizontalOverflow(ownerPage);
      await ownerPage.screenshot({ path: testInfo.outputPath("02-admin-narrow.png"), fullPage: true });
      await ownerPage.getByRole("button", { name: "서버 미리보기" }).click();
      const republishPromise = ownerPage.waitForResponse((response) => response.url().endsWith(`/api/v1/admin/publishing/studies/${environment.slug}/publish`));
      await ownerPage.getByRole("button", { name: "미리보기와 같은 버전 공개" }).click();
      const republishedResponse = await republishPromise;
      recordResponse(httpEvidence, "final-republish-revision-4", republishedResponse);
      expect(republishedResponse.status()).toBe(200);
      const republished = (await republishedResponse.json()) as StudyAdminView;
      expect(republished.applied_action).toBe("publish");
      expect(republished.applied_revision).toBe(4);

      await anonymousPage.setViewportSize({ width: 960, height: 720 });
      await anonymousPage.goto(`/studies/${environment.slug}`);
      await expect(anonymousPage.getByRole("heading", { name: `${initialContent.title} · 서버 편집 4` })).toBeVisible();
      await expectNoHorizontalOverflow(anonymousPage);
      await anonymousPage.screenshot({ path: testInfo.outputPath("03-public-narrow.png"), fullPage: true });

      const cleanupPromise = ownerPage.waitForResponse((response) => response.url().endsWith(`/api/v1/admin/publishing/studies/${environment.slug}/withdraw`));
      await ownerPage.getByRole("button", { name: "비공개로 전환" }).click();
      const cleanupResponse = await cleanupPromise;
      recordResponse(httpEvidence, "final-cleanup-withdraw", cleanupResponse);
      expect(cleanupResponse.status()).toBe(200);
      const cleaned = (await cleanupResponse.json()) as StudyAdminView;
      expect(cleaned.delivery_pending).toBe(false);
      expect(cleaned.applied_action).toBe("withdraw");
      const cleanedDetail = await anonymousContext.request.get(`${environment.publicOrigin}/api/public/studies/${environment.slug}`);
      recordResponse(httpEvidence, "final-cleanup-direct-detail", cleanedDetail);
      expect(cleanedDetail.status()).toBe(404);
    });

    expect(ownerErrors).toHaveLength(1);
    expect(ownerErrors[0]).toMatch(/^console:Failed to load resource: the server responded with a status of 409 \(Conflict\)@.+\/publish$/u);
    expect(anonymousErrors).toHaveLength(1);
    expect(anonymousErrors[0]).toMatch(/^console:Failed to load resource: the server responded with a status of 404 \(Not Found\)@.+/u);
    expect(hostileRequests).toEqual([]);
  } finally {
    const evidencePath = testInfo.outputPath("http-evidence.json");
    await writeFile(evidencePath, `${JSON.stringify(httpEvidence, null, 2)}\n`, "utf8");
    await testInfo.attach("http-evidence.json", { path: evidencePath, contentType: "application/json" });
    await ownerContext.close();
    await anonymousContext.close();
  }
});

test("public-only runtime serves anonymous studies and fails closed for private routes", async ({ browser }, testInfo) => {
  const context = await browser.newContext({ baseURL: environment.publicOnlyBaseURL });
  const page = await context.newPage();
  const errors = observeErrors(page);
  const httpEvidence: Array<Record<string, unknown>> = [];
  try {
    const publicApi = await context.request.get("/api/public/studies");
    recordResponse(httpEvidence, "public-only-public-api", publicApi);
    expect(publicApi.status()).toBe(200);
    expect(publicApi.headers()["cache-control"]).toContain("no-store");

    const publicRoute = await page.goto("/labs/rag/studies");
    if (publicRoute) recordResponse(httpEvidence, "public-only-public-page", publicRoute);
    expect(publicRoute?.status()).toBe(200);
    await expect(page.getByRole("heading", { name: "공개 연구 기록" })).toBeVisible();
    expect(errors).toEqual([
      `console:Failed to load resource: the server responded with a status of 404 (Not Found)@${environment.publicOnlyBaseURL}/favicon.ico`,
    ]);

    for (const path of [
      "/admin/publishing",
      "/workshop/learning",
      "/login",
      "/setup",
      "/api/v1/auth/me",
    ]) {
      const response = await context.request.get(path);
      recordResponse(httpEvidence, `public-only-denied:${path}`, response);
      expect(response.status(), path).toBe(404);
    }
  } finally {
    const evidencePath = testInfo.outputPath("http-evidence.json");
    await writeFile(evidencePath, `${JSON.stringify(httpEvidence, null, 2)}\n`, "utf8");
    await testInfo.attach("http-evidence.json", { path: evidencePath, contentType: "application/json" });
    await context.close();
  }
});

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`publishing_acceptance_env_missing:${name}`);
  return value;
}

function requiredSlug(name: string): string {
  const value = requiredEnvironment(name);
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/u.test(value)) throw new Error(`publishing_acceptance_slug_invalid:${name}`);
  return value;
}

function publishingMutationHeaders(): Record<string, string> {
  return {
    origin: environment.baseURL,
    "content-type": "application/json",
    "x-publishing-request": "1",
  };
}

async function fillStudyForm(page: Page, content: StudyContent): Promise<void> {
  await page.getByLabel("공개 주소 슬러그").fill(content.slug);
  await page.getByLabel("제목").fill(content.title);
  await page.getByLabel("요약").fill(content.summary);
  await page.getByLabel("기술 주제 키").fill(content.topic_keys.join(", "));
  await page.getByLabel("본문").fill(content.body);
  await page.getByLabel("검증 기록").fill(content.verification);
  await page.getByLabel("남은 한계").fill(content.limitations);
}

function observeErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`pageerror:${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") {
      const location = message.location().url;
      errors.push(`console:${message.text()}${location ? `@${location}` : ""}`);
    }
  });
  page.on("requestfailed", (request) => errors.push(`requestfailed:${request.method()}:${request.url()}:${request.failure()?.errorText ?? "unknown"}`));
  return errors;
}

function recordResponse(
  evidence: Array<Record<string, unknown>>,
  name: string,
  response: APIResponse | { request(): { method(): string }; url(): string; status(): number },
  apiMethod = "GET",
): void {
  const method = "request" in response ? response.request().method() : apiMethod;
  evidence.push({ name, method, url: response.url(), status: response.status() });
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const dimensions = await page.evaluate(() => ({ width: window.innerWidth, scrollWidth: document.documentElement.scrollWidth }));
  expect(dimensions.scrollWidth).toBeLessThanOrEqual(dimensions.width);
}

async function assertNpcStudyLink(page: Page, buttonName: string, title: string, screenshotPath?: string): Promise<void> {
  const trigger = page.getByRole("button", { name: buttonName });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("link", { name: title })).toHaveAttribute("href", `/studies/${environment.slug}`);
  if (screenshotPath) await page.screenshot({ path: screenshotPath, fullPage: true });
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
}

async function assertNpcStudyAbsent(page: Page, buttonName: string, title: string): Promise<void> {
  const trigger = page.getByRole("button", { name: buttonName });
  await trigger.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByRole("link", { name: title })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(trigger).toBeFocused();
}

async function acquirePublicStoreLock(): Promise<ChildProcessWithoutNullStreams> {
  const helper = resolve(process.cwd(), "tests/publishing/lock_public_store.py");
  const child = spawn(environment.python, [helper, "--store", environment.store, "--timeout", "20"], {
    cwd: process.cwd(),
    stdio: ["pipe", "pipe", "pipe"],
    windowsHide: true,
  });
  const stderr: string[] = [];
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (chunk: string) => stderr.push(chunk));
  const lines = createInterface({ input: child.stdout });
  await new Promise<void>((resolveReady, reject) => {
    const timer = setTimeout(() => reject(new Error(`publishing_acceptance_lock_not_ready:${stderr.join("")}`)), 5_000);
    lines.once("line", (line) => {
      clearTimeout(timer);
      if (line !== "READY") reject(new Error(`publishing_acceptance_lock_invalid_signal:${line}`));
      else resolveReady();
    });
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.once("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`publishing_acceptance_lock_early_exit:${code}:${stderr.join("")}`));
    });
  });
  lines.close();
  return child;
}

async function releasePublicStoreLock(child: ChildProcessWithoutNullStreams): Promise<void> {
  child.stdin.end("\n");
  await new Promise<void>((resolveExit, reject) => {
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error("publishing_acceptance_lock_release_timeout"));
    }, 5_000);
    child.once("exit", (code) => {
      clearTimeout(timer);
      if (code === 0) resolveExit();
      else reject(new Error(`publishing_acceptance_lock_exit:${code}`));
    });
    child.once("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
  });
}
