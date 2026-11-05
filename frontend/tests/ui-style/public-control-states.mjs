// Run from frontend: node tests/ui-style/public-control-states.mjs
// Opens public navigation/disclosures only. All non-read HTTP requests are blocked.
import assert from "node:assert/strict";
import { chromium } from "@playwright/test";
import { auditReadyPage } from "./live-control-audit.mjs";

const origin = new URL(process.env.WORKSHOP_ORIGIN ?? "http://127.0.0.1:5173");
if (!["localhost","127.0.0.1","[::1]"].includes(origin.hostname)) throw new Error("local-origin-required");
const browser = await chromium.launch({channel:process.env.UI_STYLE_BROWSER ?? "msedge",headless:true});

async function checkOpenState(page, state, selector, mobile) {
  // Record the actual focus handoff separately; give the CSS probe a neutral baseline.
  const previous = await page.evaluateHandle(() => document.activeElement);
  await page.mouse.move(0,0);
  await previous.evaluate(e => e.blur?.());
  const controls = await auditReadyPage(page,selector);
  await previous.evaluate(e => e.isConnected && e.focus?.({preventScroll:true}));
  await previous.dispose();
  const failures = controls.map((c,index) => ({...c,index})).filter(c =>
    c.short || (c.disabled && c.hoverChanged) || (!c.disabled && (!c.keyboard || !c.focusChanged || (!mobile && !c.hoverChanged))));
  const horizontalOverflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1);
  console.log(JSON.stringify({mobile,state,count:controls.length,horizontalOverflow,failures}));
  if (failures.length || horizontalOverflow || !controls.length) process.exitCode=1;
}

async function visit(page,path) {
  const response = await page.goto(new URL(path,origin).href,{waitUntil:"networkidle",timeout:30000});
  assert.ok(response?.ok());
}

async function drawer(page) {
  await visit(page,"/labs");
  const trigger=page.getByRole("button",{name:"메뉴 열기"});
  await trigger.click();
  const panel=page.locator("dialog[open]");
  await panel.waitFor();
  const stops=panel.locator("a[href]:visible,button:enabled:visible,summary:visible");
  const first=stops.first(), last=stops.last();
  await first.focus();
  await page.keyboard.press("Shift+Tab");
  assert.ok(await last.evaluate(e=>e===document.activeElement));
  await page.keyboard.press("Tab");
  assert.ok(await first.evaluate(e=>e===document.activeElement));
  await checkOpenState(page,"navigation-drawer","dialog[open]",true);
  await page.keyboard.press("Escape");
  await panel.waitFor({state:"hidden"});
  assert.ok(await trigger.evaluate(e=>e===document.activeElement));
}

async function guide(page,mobile) {
  await visit(page,"/");
  const panel=page.getByRole("complementary",{name:"이동 안내"});
  const button=panel.getByRole("button");
  const initial=await button.getAttribute("aria-expanded");
  for (let i=0;i<2;i++) {
    await button.click();
    const open=await button.getAttribute("aria-expanded")==="true";
    assert.equal(await page.locator("#office-guide-content").isVisible(),open);
    await checkOpenState(page,open?"office-guide-open":"office-guide-collapsed",'aside:has(button[aria-controls="office-guide-content"])',mobile);
  }
  assert.equal(await button.getAttribute("aria-expanded"),initial);
}

async function category(page,mobile) {
  await visit(page,"/labs/rag/studies");
  const trigger=page.getByRole("button",{name:/^카테고리:/});
  await trigger.click();
  const dialog=page.getByRole("dialog",{name:"카테고리 선택"});
  const search=dialog.getByRole("searchbox");
  assert.ok(await search.evaluate(e => e===document.activeElement));
  const box=await search.boundingBox();
  assert.ok(box && box.width>=44 && box.height>=44,"search-target");
  await checkOpenState(page,"category-open",'[role="dialog"]',mobile);
  await search.fill("__no_synthetic_match__");
  assert.equal(await dialog.getByRole("listitem").count(),0);
  await checkOpenState(page,"category-filter-empty",'[role="dialog"]',mobile);
  await dialog.getByRole("button",{name:"검색어 지우기"}).click();
  assert.equal(await search.inputValue(),"");
  assert.ok(await search.evaluate(e => e===document.activeElement));
  await page.keyboard.press("Escape");
  await dialog.waitFor({state:"hidden"});
  assert.ok(await trigger.evaluate(e=>e===document.activeElement));
  await trigger.click();
  const option=dialog.getByRole("listitem").first().getByRole("link");
  const href=new URL(await option.getAttribute("href"),origin);
  assert.equal(href.pathname,"/labs/rag/studies");
  assert.ok(href.searchParams.has("topic"));
  await option.click();
  await page.waitForURL(href.href);
  await dialog.waitFor({state:"hidden"});
}

async function ragDialogs(page,mobile) {
  await visit(page,"/labs/rag");
  const triggers=page.getByRole("button",{name:/에게 말 걸기$/});
  const count=await triggers.count();
  assert.ok(count>0);
  for (let i=0;i<count;i++) {
    const trigger=triggers.nth(i);
    await trigger.click();
    const dialog=page.getByRole("dialog");
    await dialog.waitFor();
    assert.ok(await dialog.evaluate(e => e.contains(document.activeElement)));
    await checkOpenState(page,`rag-dialog-${i+1}`,'[role="dialog"]',mobile);
    await page.keyboard.press("Escape");
    await dialog.waitFor({state:"hidden"});
    assert.ok(await trigger.evaluate(e=>e===document.activeElement));
  }
}

try {
  for (const mobile of [false,true]) {
    const context=await browser.newContext({viewport:{width:mobile?375:1440,height:mobile?812:900},
      isMobile:mobile,hasTouch:mobile,reducedMotion:"reduce",serviceWorkers:"block"});
    let blockedWrites=0;
    await context.route("**/*",route=>{
      if (["GET","HEAD","OPTIONS"].includes(route.request().method())) return route.continue();
      blockedWrites++; return route.abort();
    });
    const page=await context.newPage();
    for (const scenario of mobile?[drawer,guide,category,ragDialogs]:[guide,category,ragDialogs]) {
      try { await scenario(page,mobile); }
      catch(error) {
        // Error messages from locators may contain content; report only our phase and class.
        console.log(JSON.stringify({mobile,scenario:scenario.name,error:error.name,where:error.stack?.match(/public-control-states\.mjs:(\d+)/)?.[1]}));
        process.exitCode=1;
      }
    }
    console.log(JSON.stringify({mobile,blockedWrites}));
    if (blockedWrites) process.exitCode=1;
    await context.close();
  }
} finally { await browser.close(); }
