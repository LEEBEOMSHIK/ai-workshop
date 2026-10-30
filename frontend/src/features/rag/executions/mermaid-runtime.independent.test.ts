import { afterEach, beforeEach, expect, it, vi } from "vitest";

beforeEach(() => { vi.resetModules(); vi.useFakeTimers(); });
afterEach(() => {
  document.head.querySelectorAll("script").forEach(script => script.remove());
  vi.unstubAllGlobals(); vi.useRealTimers();
});

it("rejects a runtime initialization failure instead of leaving graph loading unresolved", async () => {
  const initialize = vi.fn(() => { throw new Error("SYNTHETIC_INITIALIZATION_FAILURE"); });
  vi.stubGlobal("mermaid", { initialize, render: vi.fn() });
  const { loadMermaid } = await import("./mermaid-runtime");
  const settled = vi.fn();
  const loading = loadMermaid().then(() => settled("ready"), error => settled(error instanceof Error ? error.message : String(error)));
  const script = document.head.querySelector("script")!;
  expect(script).not.toBeNull();
  expect(() => script.onload?.call(script, new Event("load"))).not.toThrow();
  await loading;
  expect(settled).toHaveBeenCalledExactlyOnceWith("diagram_runtime_unavailable");
  expect(document.head.querySelector("script")).toBeNull();
});

it("initializes strict local rendering without HTML labels or Mermaid start-on-load scanning", async () => {
  const initialize = vi.fn();
  const runtime = { initialize, render: vi.fn() };
  vi.stubGlobal("mermaid", runtime);
  const { loadMermaid } = await import("./mermaid-runtime");
  const loading = loadMermaid();
  const script = document.head.querySelector("script")!;
  script.onload?.call(script, new Event("load"));
  await expect(loading).resolves.toBe(runtime);
  expect(initialize).toHaveBeenCalledWith(expect.objectContaining({
    startOnLoad: false, securityLevel: "strict", htmlLabels: false,
    suppressErrorRendering: true, logLevel: "fatal",
    flowchart: expect.objectContaining({ htmlLabels: false }),
  }));
  expect(new URL(script.src).host).toBe(window.location.host);
});
