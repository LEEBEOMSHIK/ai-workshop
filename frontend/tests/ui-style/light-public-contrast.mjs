// Run against the existing local app from frontend: node tests/ui-style/light-public-contrast.mjs
// Screenshots stay in memory. This browser context has no account or existing preferences.
import { chromium } from "@playwright/test";
import { createRequire } from "node:module";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import assert from "node:assert/strict";

const require = createRequire(import.meta.url);
const sharp = createRequire(require.resolve("next/package.json"))("sharp");
const origin = new URL(process.env.WORKSHOP_ORIGIN ?? "http://127.0.0.1:5173");
if (!["localhost","127.0.0.1","[::1]"].includes(origin.hostname)) throw new Error("local-origin-required");
const maskText = "*,*::before,*::after,*::placeholder { -webkit-text-fill-color: transparent !important; text-shadow:none !important; caret-color:transparent !important } svg text {fill:transparent !important}";

function luminance(rgb) {
  return rgb.reduce((sum,v,i) => {
    const s=v/255;
    return sum+[.2126,.7152,.0722][i]*(s<=.04045?s/12.92:((s+.055)/1.055)**2.4);
  },0);
}

function collectText(scope) {
  const root = document.querySelector(scope);
  if (!root) return [];
  const walker=document.createTreeWalker(root,NodeFilter.SHOW_TEXT);
  const samples=[];
  const canvas=document.createElement("canvas").getContext("2d");
  function add(el,rect,style) {
    if (!rect.width || !rect.height || el.closest(":disabled,[aria-disabled=true],nextjs-portal,[inert]")) return;
    const ys=rect.y+rect.height*.5;
    if (ys<1 || ys>=innerHeight-1) return;
    const opacity=Number(style.opacity);
    canvas.clearRect(0,0,1,1); canvas.fillStyle=el instanceof SVGTextElement ? style.fill : style.webkitTextFillColor || style.color; canvas.fillRect(0,0,1,1);
    const fg=[...canvas.getImageData(0,0,1,1).data];
    if (!fg[3]) return;
    for (const f of [.22,.5,.78]) {
      const x=rect.x+rect.width*f;
      if (x<1 || x>=innerWidth-1) continue;
      const hit=document.elementFromPoint(x,ys);
      if (!(el.contains(hit) || style.pointerEvents==="none")) continue;
      samples.push({x:Math.floor(x),y:Math.floor(ys),fg,opacity,
        tag:el.localName,cls:el.getAttribute("class") || el.parentElement?.getAttribute("class") || "",
        large:parseFloat(style.fontSize)>=(parseInt(style.fontWeight)>=700?18.66:24)});
    }
  }
  for (let text=walker.nextNode();text;text=walker.nextNode()) {
    const el=text.parentElement;
    if (!text.nodeValue.trim() || !el || el.closest("style,script,option") || !el.checkVisibility({visibilityProperty:true,opacityProperty:true})) continue;
    const r=document.createRange(); r.selectNodeContents(text);
    const css=getComputedStyle(el);
    for(const line of r.getClientRects()) add(el,line,css);
  }
  for(const el of root.querySelectorAll("input:not([type=checkbox],[type=radio]),textarea")) {
    if (!el.checkVisibility({visibilityProperty:true,opacityProperty:true})) continue;
    add(el,el.getBoundingClientRect(),getComputedStyle(el));
  }
  return samples;
}

export async function auditTextContrast(page,scope="body",scroller) {
  const problems = new Map();
  const scrollTarget=page.locator(scroller ?? "html").first();
  const extent=await scrollTarget.evaluate(e=>({height:e.scrollHeight,view:e.clientHeight}));
  let total=0;
  for(let y=0;y<extent.height;y+=Math.max(240,extent.view-64)) {
    await scrollTarget.evaluate((e,top)=>e.scrollTo({top,behavior:"instant"}),y);
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    const samples=await page.evaluate(collectText,scope);
    if(!samples.length) continue;
    const screenshot=await page.screenshot({animations:"disabled",style:maskText});
    const {data,info}=await sharp(screenshot).removeAlpha().raw().toBuffer({resolveWithObject:true});
    for(const s of samples) {
      if(s.x>=info.width || s.y>=info.height) continue;
      const offset=(s.y*info.width+s.x)*info.channels;
      const bg=[...data.subarray(offset,offset+3)], a=s.fg[3]/255*s.opacity;
      const fg=s.fg.slice(0,3).map((v,i)=>v*a+bg[i]*(1-a));
      const l1=luminance(fg),l2=luminance(bg),ratio=(Math.max(l1,l2)+.05)/(Math.min(l1,l2)+.05);
      total++;
      if(ratio+.005<(s.large?3:4.5)) {
        const key=[s.tag,s.cls].join("|");
        const old=problems.get(key);
        if(!old || old.ratio>ratio) problems.set(key,{tag:s.tag,cls:s.cls,ratio,fg:s.fg.slice(0,3),bg});
      }
    }
    if (y+extent.view>=extent.height) break;
  }
  await scrollTarget.evaluate(e=>e.scrollTo({top:0,behavior:"instant"}));
  return {samples:total,failures:[...problems.values()].map(x=>({...x,ratio:+x.ratio.toFixed(2)}))};
}

async function inspect(page,state,scope,scroller) {
  const result=await auditTextContrast(page,scope,scroller);
  console.log(JSON.stringify({state,...result}));
  if(result.failures.length || !result.samples) process.exitCode=1;
}

async function publicAudit() {
const browser = await chromium.launch({channel:process.env.UI_STYLE_BROWSER ?? "msedge", headless:true});
try {
  for (const mobile of [false,true]) {
    const context=await browser.newContext({viewport:{width:mobile?375:1440,height:mobile?812:900},isMobile:mobile,hasTouch:mobile,reducedMotion:"reduce",serviceWorkers:"block"});
    await context.route("**/*",r=>["GET","HEAD","OPTIONS"].includes(r.request().method())?r.continue():r.abort());
    const page=await context.newPage();
    const visit=async path=>{const r=await page.goto(new URL(path,origin).href,{waitUntil:"networkidle"});assert.ok(r?.ok());};
    await visit("/login");
    if(mobile) await page.getByRole("button",{name:"메뉴 열기"}).click();
    await page.getByRole("button",{name:"화면 설정",exact:true}).click();
    await page.getByRole("radio",{name:"라이트",exact:true}).check();
    const prefix=mobile?"mobile":"desktop";
    if(mobile) await inspect(page,prefix+"-drawer",'dialog[open]','dialog[open]');
    let detail;
    for(const route of ["/","/labs","/labs/rag","/labs/rag/studies","detail","/login","/setup"]) {
      if(route==="detail" && !detail) throw new Error("no-published-study-link");
      await visit(route==="detail"?detail:route);
      assert.equal(await page.locator("html").getAttribute("data-theme"),"light");
      if(route==="/setup" && new URL(page.url()).pathname==="/login") { console.log(prefix+" /setup -> /login"); continue; }
      await inspect(page,prefix+route);
      if (!mobile) {
        const session=await context.newCDPSession(page);
        try {
          await session.send("DOM.enable");await session.send("CSS.enable");
          const {root}=await session.send("DOM.getDocument");
          const {nodeIds}=await session.send("DOM.querySelectorAll",{nodeId:root.nodeId,selector:"a[href],button:enabled,summary"});
          for(const nodeId of nodeIds) await session.send("CSS.forcePseudoState",{nodeId,forcedPseudoClasses:["hover"]});
          await inspect(page,prefix+route+"-hover");
        } finally { await session.detach(); }
      }
      if(route==="/labs/rag/studies") {
        detail=await page.locator('main a[href^="/studies/"]').first().getAttribute("href");
        await page.getByRole("button",{name:/^카테고리:/}).click();
        await inspect(page,prefix+"-categories",'[role="dialog"]');
        await page.getByRole("dialog").getByRole("listitem").first().getByRole("link").click();
        await page.waitForURL(url=>url.searchParams.has("topic"));
        await page.getByRole("button",{name:/^카테고리:/}).click();
        await inspect(page,prefix+"-selected-category",'[role="dialog"]');
      }
      if(route==="/labs/rag") {
        const triggers=page.getByRole("button",{name:/에게 말 걸기$/});
        for(let i=0;i<await triggers.count();i++) {
          await triggers.nth(i).click();
          await page.locator('[role="dialog"][data-placement]').waitFor();
          await inspect(page,prefix+"-rag-popup-"+i,'[role="dialog"]','[role="dialog"] [class*="dialogCopy"]');
          await page.keyboard.press("Escape");
        }
      }
    }
    await context.close();
  }
} finally { await browser.close(); }
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href===import.meta.url) await publicAudit();
