import { resolveApiTarget } from "./api-target";

describe("resolveApiTarget", () => {
  it("uses the configured local API port instead of a hardcoded target", () => {
    expect(resolveApiTarget("18000")).toBe("http://127.0.0.1:18000");
  });

  it("uses the documented local default", () => {
    expect(resolveApiTarget(undefined)).toBe("http://127.0.0.1:8000");
    expect(resolveApiTarget("  ")).toBe("http://127.0.0.1:8000");
  });

  it.each(["invalid", "0", "65536", "1.5"])(
    "rejects invalid TCP port %s",
    (port) => {
      expect(() => resolveApiTarget(port)).toThrow("API_PORT");
    },
  );
});
