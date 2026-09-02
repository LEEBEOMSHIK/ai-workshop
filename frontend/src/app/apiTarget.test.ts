import { resolveApiTarget } from "./apiTarget";

describe("resolveApiTarget", () => {
  it("uses the configured local API port instead of a hardcoded proxy target", () => {
    expect(resolveApiTarget("18000")).toBe("http://127.0.0.1:18000");
  });

  it("keeps the documented default and rejects invalid ports", () => {
    expect(resolveApiTarget(undefined)).toBe("http://127.0.0.1:8000");
    expect(() => resolveApiTarget("invalid")).toThrow("API_PORT");
  });
});
