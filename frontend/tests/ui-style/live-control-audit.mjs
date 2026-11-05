// Run from frontend: node tests/ui-style/live-control-audit.mjs
// Read-only. Inspect rendered controls without clicking them or emitting key events.
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { chromium } from "@playwright/test";

const controlSelector = "a[href],button,input:is([type=submit],[type=reset],[type=button]),[role=button],[role=link],[aria-disabled=true][aria-label],summary";
const paintProperties = ["backgroundColor","backgroundImage","color","borderTopColor","borderRightColor","borderBottomColor",
  "borderLeftColor","boxShadow","textDecorationLine","textDecorationColor","opacity","filter","transform","fill","stroke",
  "outlineStyle","outlineColor","outlineWidth"];

// Executed in the page. Only numeric measurements and computed styles are returned.
async function inspect(properties, metadata) {
  // CDP invokes this function on the resolved DOM element.
  if (metadata) {
    const {width,height} = this.getBoundingClientRect();
    if (!width || !height || !this.checkVisibility({visibilityProperty:true,opacityProperty:true}) ||
        this.closest("[inert], [hidden], nextjs-portal")) return null;
    const inlineText = this.matches("a") && getComputedStyle(this).display === "inline" &&
      this.parentElement && [...this.parentElement.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    return {tag:this.localName, classes:[...this.classList].slice(0,4), width:Math.round(width*10)/10, height:Math.round(height*10)/10,
      disabled:this.matches(":disabled,[aria-disabled=true]"), keyboard:this.tabIndex >= 0 || this.matches("summary"),
      inline: Boolean(inlineText), short: !inlineText && (width < 43.99 || height < 43.99)};
  }
  this.getBoundingClientRect();
  const transitions = this.getAnimations({subtree:true}).filter(a => a instanceof CSSTransition);
  await Promise.allSettled(transitions.map(a => a.finished));
  const nodes = [this, ...this.querySelectorAll("*")];
  const paints = [];
  for (const node of nodes) {
    if (!node.checkVisibility({visibilityProperty:true,opacityProperty:true})) continue;
    for (const pseudo of [null,"::before","::after"]) {
      const css = getComputedStyle(node,pseudo);
      if (pseudo && ["none","normal"].includes(css.content)) continue;
      paints.push(properties.map(prop => {
        if (prop.startsWith("outline") && (css.outlineStyle === "none" || css.outlineWidth === "0px")) return "";
        if (prop === "boxShadow" && /^rgba\(0, 0, 0, 0\) [^,]*$/.test(css.boxShadow)) return "none";
        return css[prop];
      }));
    }
  }
  return paints;
}

export async function auditReadyPage(page, scope) {
  const session = await page.context().newCDPSession(page);
  const controls = [];
  try {
    await session.send("DOM.enable");
    await session.send("CSS.enable");
    const {root} = await session.send("DOM.getDocument");
    const container = scope ? await session.send("DOM.querySelector",{nodeId:root.nodeId,selector:scope}) : root;
    if (!container.nodeId) throw new Error("missing-audit-scope");
    const {nodeIds} = await session.send("DOM.querySelectorAll",{nodeId:container.nodeId,selector:controlSelector});
    for (const nodeId of nodeIds) {
      const {object} = await session.send("DOM.resolveNode",{nodeId});
      const read = async metadata => {
        const result = await session.send("Runtime.callFunctionOn", {objectId:object.objectId,
          functionDeclaration:inspect.toString(), arguments:[{value:paintProperties},{value:metadata}],
          awaitPromise:true, returnByValue:true});
        if (result.exceptionDetails) throw new Error("control-inspection-failed");
        return result.result.value;
      };
      const info = await read(true);
      if (!info) continue;
      const force = pseudo => session.send("CSS.forcePseudoState",{nodeId,forcedPseudoClasses:pseudo});
      const before = JSON.stringify(await read(false));
      await force(["hover"]);
      const hoverChanged = JSON.stringify(await read(false)) !== before;
      await force(["focus","focus-visible"]);
      const focusChanged = JSON.stringify(await read(false)) !== before;
      await force([]);
      controls.push({...info, hoverChanged, focusChanged});
    }
    return controls;
  } finally { await session.detach(); }
}

async function publicAudit() {
  const origin = new URL(process.env.WORKSHOP_ORIGIN ?? "http://127.0.0.1:5173");
  if (!["127.0.0.1","localhost","[::1]"].includes(origin.hostname)) throw new Error("local-origin-required");
  const browser = await chromium.launch({channel:process.env.UI_STYLE_BROWSER ?? "msedge", headless:true});
  try {
    const context = await browser.newContext({viewport:{width:1440,height:900}, reducedMotion:"reduce", serviceWorkers:"block"});
    await context.route("**/*", route => ["GET","HEAD","OPTIONS"].includes(route.request().method()) ? route.continue() : route.abort());
    const page = await context.newPage();
    let detail;
    for (const route of ["/","/labs","/labs/rag","/labs/rag/studies","/studies/[publicSlug]","/login","/setup"]) {
      const path = route === "/studies/[publicSlug]" ? detail : route;
      if (!path) { console.log(JSON.stringify({route,status:"no-published-detail-link",unverified:true})); process.exitCode=1; continue; }
      try {
        const response = await page.goto(new URL(path,origin).href,{waitUntil:"domcontentloaded",timeout:30000});
        await page.waitForLoadState("networkidle",{timeout:8000}).catch(() => {});
        const status = response?.status();
        if (new URL(page.url()).pathname !== path) {
          const setupComplete = route === "/setup" && new URL(page.url()).pathname === "/login";
          console.log(JSON.stringify({route,status,redirected:setupComplete ? "/login" : true}));
          if (!setupComplete) process.exitCode=1;
          continue;
        }
        if (!response?.ok() || await page.locator("[data-upstream-status], nextjs-error").count()) {
          console.log(JSON.stringify({route,status,errorPage:true,unverified:true})); process.exitCode=1; continue;
        }
        if (route === "/labs/rag/studies") {
          const href = await page.locator('main a[href^="/studies/"]').first().getAttribute("href",{timeout:2000}).catch(() => null);
          if (href) {
            const linked = new URL(href,origin);
            if (linked.origin === origin.origin && /^\/studies\/[^/?#]+\/?$/.test(linked.pathname)) detail = linked.pathname;
          }
        }
        const controls = await auditReadyPage(page);
        const failures = controls.map((c,i) => ({...c,index:i})).filter(c =>
          c.short || c.hoverChanged === c.disabled || (!c.disabled && (!c.keyboard || !c.focusChanged)));
        console.log(JSON.stringify({route,status,count:controls.length,failures}));
        if (failures.length) process.exitCode=1;
      } catch (error) { console.log(JSON.stringify({route,error:error.name})); process.exitCode=1; }
    }
  } finally { await browser.close(); }
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  await publicAudit();
}
