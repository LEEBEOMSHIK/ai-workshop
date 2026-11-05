// Run from frontend: node tests/ui-style/theme-browser.mjs
// Uses the public shell and a disposable browser context, with no account or data writes.
import assert from "node:assert/strict";
import { chromium } from "@playwright/test";

const origin = new URL(process.env.WORKSHOP_ORIGIN ?? "http://127.0.0.1:5173");
if (!["localhost","127.0.0.1","[::1]"].includes(origin.hostname)) throw new Error("local-origin-required");
const browser = await chromium.launch({channel:process.env.UI_STYLE_BROWSER ?? "msedge",headless:true});
try {
  const context = await browser.newContext({viewport:{width:1440,height:900},serviceWorkers:"block"});
  await context.route("**/*", route => ["GET","HEAD","OPTIONS"].includes(route.request().method()) ? route.continue() : route.abort());
  await context.addInitScript(() => {
    function readFirstFrame() {
      if (!document.body || !document.querySelector("main")) return requestAnimationFrame(readFirstFrame);
      window.firstWorkshopFrame = document.documentElement.dataset.theme;
    }
    requestAnimationFrame(readFirstFrame);
  });
  const settings = await context.newPage();
  const peer = await context.newPage();
  await settings.goto(new URL("/login",origin).href);
  await peer.goto(new URL("/labs",origin).href);
  const themeIs = (page,theme) => page.waitForFunction(value => document.documentElement.dataset.theme === value,theme);
  const trigger = settings.getByRole("button",{name:"화면 설정",exact:true});
  await trigger.click();
  assert.equal(await settings.getByRole("radio",{name:"다크",exact:true}).isChecked(),true);
  await settings.getByRole("radio",{name:"라이트",exact:true}).check();
  await Promise.all([themeIs(settings,"light"),themeIs(peer,"light")]);
  const color = await settings.locator('input[type="email"]').evaluate(input => getComputedStyle(input).backgroundColor);
  await settings.reload();
  await settings.waitForFunction(() => Boolean(window.firstWorkshopFrame));
  assert.equal(await settings.evaluate(() => window.firstWorkshopFrame),"light");
  assert.equal(await settings.locator('input[type="email"]').evaluate(input => getComputedStyle(input).backgroundColor),color);
  await trigger.click();
  assert.equal(await settings.getByRole("radio",{name:"라이트",exact:true}).isChecked(),true);
  await settings.getByRole("radio",{name:"다크",exact:true}).check();
  await Promise.all([themeIs(settings,"dark"),themeIs(peer,"dark")]);
  assert.notEqual(await settings.locator('input[type="email"]').evaluate(input => getComputedStyle(input).backgroundColor),color);
  console.log("Theme: initial content frame, input surface, reload, cross-tab updates and dark restoration passed.");
} finally { await browser.close(); }
