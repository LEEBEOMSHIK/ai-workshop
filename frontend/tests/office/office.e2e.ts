import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import type { officeMap as MapFixture } from "../../src/features/office-game/map";
import { OFFICE } from "../../src/features/office-game/config";

const officeMap: typeof MapFixture = JSON.parse(readFileSync(resolve(process.cwd(), "public/office/maps/office.json"), "utf8"));
const objects = (name: string) => officeMap.layers.find((layer) => layer.name === name)!.objects!;
const world = {
  npcs: objects("NPC").filter((entry) => entry.type === "npc").map((entry) => ({ ...entry, id: entry.name })),
  collisions: objects("Collision").map((entry) => ({ ...entry, id: entry.name })),
};
const crossing = officeMap.layers.find((layer) => layer.name === "Navigation")!.objects!.find((area) => area.name === "lobby-crossing")!;

const stage = (page: Page) => page.getByRole("application");
async function position(page: Page) {
  const target = page.getByLabel("플레이어 위치");
  return {
    x: Number(await target.getAttribute("data-x")),
    y: Number(await target.getAttribute("data-y")),
  };
}
async function hold(page: Page, key: string, duration: number) {
  await page.keyboard.down(key);
  try { await page.waitForTimeout(duration); }
  finally { await page.keyboard.up(key); }
  await page.waitForTimeout(150);
}
async function enter(page: Page) {
  await page.goto("/");
  await expect(page.locator("canvas")).toHaveCount(1);
  await expect.poll(async () => (await position(page)).y).toBeGreaterThan(0);
  await stage(page).click();
}
async function moveAxis(page: Page, axis: "x" | "y", target: number) {
  const current = (await position(page))[axis];
  if (Math.abs(target - current) < 12) return;
  const key = axis === "x" ? (target > current ? "d" : "a") : (target > current ? "s" : "w");
  await page.keyboard.down(key);
  try {
    await expect.poll(async () => (await position(page))[axis], { intervals: [20], timeout: 8000 })[target > current ? "toBeGreaterThanOrEqual" : "toBeLessThanOrEqual"](target);
  } finally { await page.keyboard.up(key); }
  await page.waitForTimeout(200);
}
async function approach(page: Page, id: string) {
  const npc = world.npcs.find((entry) => entry.id === id)!;
  await moveAxis(page, "y", crossing.y + crossing.height / 2);
  await moveAxis(page, "x", npc.x);
  await moveAxis(page, "y", npc.y + OFFICE.interactionRadius * .8);
}
async function clickNpc(page: Page, id: string) {
  const npc = world.npcs.find((entry) => entry.id === id)!;
  const box = (await stage(page).boundingBox())!;
  const player = await position(page);
  const scrollX = Math.max(0, Math.min(officeMap.width * officeMap.tilewidth - box.width, player.x - box.width / 2));
  const scrollY = Math.max(0, Math.min(officeMap.height * officeMap.tileheight - box.height, player.y - box.height / 2));
  await stage(page).click({ position: { x: npc.x - scrollX, y: npc.y - OFFICE.actorHeight / 2 - scrollY } });
}

test("walk from lobby to NPC, React dialogue locks movement and restores input", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await enter(page);
  const initial = await position(page);
  await approach(page, "rag-chief");
  await expect(page.getByRole("button", { name: /RAG 총괄 · 대화/ })).toBeVisible();
  expect((await position(page)).y).toBeLessThan(initial.y - 300);
  await page.keyboard.press("e");
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("link", { name: /RAG/ })).toHaveAttribute("href", "/labs/rag");
  const stopped = await position(page);
  await hold(page, "ArrowDown", 400);
  expect(await position(page)).toEqual(stopped);
  await page.keyboard.press("Escape");
  await expect(dialog).not.toBeVisible();
  await page.keyboard.press("e");
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "대화 닫기" }).click();
  await expect(dialog).not.toBeVisible();
  await hold(page, "ArrowDown", 650);
  expect((await position(page)).y).toBeGreaterThan(stopped.y + 50);
  await expect(page.getByRole("button", { name: /RAG 총괄 · 대화/ })).not.toBeVisible();
  expect(errors).toEqual([]);
});

test("furniture has collision and missing map gives an accessible recovery route", async ({ page }) => {
  await enter(page);
  const sofa = world.collisions.find((entry) => entry.id === "decor-lobby-sofa-west")!;
  await moveAxis(page, "y", crossing.y + crossing.height / 2);
  await moveAxis(page, "x", sofa.x + sofa.width / 2);
  await hold(page, "s", 1200);
  const desk = await position(page);
  expect(desk.x).toBeGreaterThan(sofa.x);
  expect(desk.y).toBeLessThanOrEqual(sofa.y + 1);
  expect(desk.y).toBeGreaterThanOrEqual(sofa.y - 3);
  await hold(page, "s", 300);
  expect((await position(page)).y).toBe(desk.y);
  await page.route("**/office/maps/office.json", (route) => route.abort());
  await page.reload();
  await expect(page.getByRole("alert").filter({ hasText: "게임 화면을 불러오지 못했습니다" })).toBeVisible();
  await expect(page.getByRole("link", { name: "AI Labs", exact: true })).toBeVisible();
});

test("selects each clicked character, preserves focus and enters RAG directly", async ({ page }) => {
  await enter(page);
  await approach(page, "founder");
  await clickNpc(page, "founder");
  const founder = page.getByRole("dialog", { name: "LEE BEOMSHIK" });
  await expect(founder).toBeVisible();
  await expect(founder.getByRole("list", { name: "공개 연구 방향" }).getByRole("listitem")).toHaveCount(3);
  await expect(founder).toContainText("공개 소개 연출");
  const stopped = await position(page);
  await hold(page, "s", 300);
  expect(await position(page)).toEqual(stopped);
  await page.keyboard.press("Escape");
  await expect(stage(page)).toBeFocused();
  await page.keyboard.press("e");
  await expect(founder).toBeVisible();
  await founder.getByRole("button", { name: "대화 닫기" }).click();
  await approach(page, "rag-chief");
  await clickNpc(page, "rag-chief");
  await page.getByRole("link", { name: /RAG 연구소 들어가기/ }).click();
  await expect(page).toHaveURL(/\/labs\/rag$/);
  await expect(page.locator("canvas")).toHaveCount(0);
  await page.getByRole("button", { name: "구조 분석가 루미에게 말 걸기" }).click();
  await expect(page.getByRole("dialog")).toContainText("다음 인계");
  await page.keyboard.press("Escape");
  await page.getByRole("link", { name: /사장실.*로비로 돌아가기/ }).click();
  await expect(page.locator("canvas")).toHaveCount(1);
});

test("walls stop movement; focus loss, resize and route re-entry are safe", async ({ page }) => {
  await enter(page);
  const southWall = world.collisions.find((entry) => entry.id === "south")!;
  await moveAxis(page, "x", southWall.x + southWall.width - 64);
  await hold(page, "s", 1800);
  const wall = await position(page);
  await hold(page, "s", 450);
  expect((await position(page)).y).toBeCloseTo(wall.y, 0);
  expect(wall.y).toBeCloseTo(southWall.y, 0);
  await page.getByRole("link", { name: "AI Labs", exact: true }).focus();
  await hold(page, "w", 350);
  expect(await position(page)).toEqual(wall);
  await page.setViewportSize({ width: 960, height: 640 });
  await expect.poll(async () => (await page.locator("canvas").boundingBox())?.width).toBeLessThanOrEqual(960);
  await expect(page.locator("canvas")).toHaveCount(1);
  await page.getByRole("link", { name: "AI Labs", exact: true }).click();
  await expect(page).toHaveURL(/\/labs$/);
  await expect(page.locator("canvas")).toHaveCount(0);
  await page.getByRole("link", { name: "AI Workshop", exact: true }).click();
  await expect(page.locator("canvas")).toHaveCount(1);
  await expect.poll(async () => (await position(page)).y).toBeGreaterThan(0);
});

test("walks into all preparing rooms and opens recruitment boards by click and E", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await enter(page);
  await page.getByRole("button", { name: "이동 안내 접기" }).click();
  await stage(page).focus();
  const hall = objects("Navigation").find((area) => area.name === "preparing-crossing")!;
  for (const [id, title] of [["finetuning", "파인튜닝 연구소"], ["study", "AI 공부실"], ["ontology", "온톨로지 연구소"]]) {
    const notice = objects("Notices").find((entry) => entry.name === id)!;
    await moveAxis(page, "y", hall.y + hall.height / 2);
    await moveAxis(page, "x", notice.x);
    await moveAxis(page, "y", notice.y - 80);
    await expect(page.getByRole("button", { name: new RegExp(`${title}.*안내`) })).toBeVisible();
    await page.waitForTimeout(300);
    const box = (await stage(page).boundingBox())!, player = await position(page);
    const sx = Math.max(0, Math.min(officeMap.width * officeMap.tilewidth - box.width, player.x - box.width / 2));
    const sy = Math.max(0, Math.min(officeMap.height * officeMap.tileheight - box.height, player.y - box.height / 2));
    await stage(page).click({ position: { x: notice.x - sx, y: notice.y - sy } });
    const dialog = page.getByRole("dialog", { name: title });
    await expect(dialog).toContainText("관리자 모집 중 · 기능 준비 중");
    await expect(dialog.getByRole("link")).toHaveCount(0);
    const stopped = await position(page);
    await hold(page, "s", 300); expect(await position(page)).toEqual(stopped);
    await page.keyboard.press("Escape"); await expect(stage(page)).toBeFocused();
    await page.keyboard.press("e"); await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "대화 닫기" }).click();
    await expect(stage(page)).toBeFocused();
  }
  expect(errors).toEqual([]);
});

test("keeps Founder close visible and clickable below the header on a short viewport", async ({ page }) => {
  await page.setViewportSize({ width: 960, height: 640 });
  await enter(page);
  await approach(page, "founder");
  await page.keyboard.press("e");
  const dialog = page.getByRole("dialog", { name: "LEE BEOMSHIK" });
  const header = (await page.locator("header").first().boundingBox())!;
  const box = (await dialog.boundingBox())!;
  expect(box.y).toBeGreaterThanOrEqual(header.y + header.height);
  expect(box.y + box.height).toBeLessThanOrEqual(640);
  const close = dialog.getByRole("button", { name: "대화 닫기" });
  await close.click();
  await expect(dialog).not.toBeVisible();
  await expect(stage(page)).toBeFocused();
});

test("keeps all six desks in reading order across connected wide, tablet and mobile floors", async ({ page }) => {
  for (const [width, columns] of [[1440, 3], [960, 2], [640, 1]]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/labs/rag");
    const stations = page.getByRole("region", { name: "RAG 작업 파이프라인" }).getByRole("listitem");
    await expect(stations).toHaveCount(6);
    const layout = await stations.evaluateAll((elements) => elements.map((element) => {
      const rect = element.getBoundingClientRect();
      return { x: rect.x, y: rect.y, right: rect.right, bottom: rect.bottom, floorLine: getComputedStyle(element, "::after").backgroundImage };
    }));
    for (let index = 0; index < layout.length; index++) {
      expect(layout[index].floorLine).not.toBe("none");
      expect(layout[index].x).toBeGreaterThanOrEqual(0);
      expect(layout[index].right).toBeLessThanOrEqual(width);
      if (index % columns > 0) {
        expect(layout[index].y).toBeCloseTo(layout[index - 1].y, 0);
        expect(layout[index].x).toBeGreaterThan(layout[index - 1].right);
      } else if (index >= columns) {
        expect(layout[index].y).toBeGreaterThan(layout[index - columns].bottom);
        expect(layout[index].x).toBeCloseTo(layout[index - columns].x, 0);
      }
    }
  }
});
