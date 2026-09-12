import { config, decideRouteAccess } from "./proxy";

describe("route proxy boundary", () => {
  it("captures return paths only for protected areas", () => {
    expect(config.matcher).toContain("/workshop/:path*");
    expect(config.matcher).toContain("/admin/:path*");
  });

  it("makes private UI and API routes unavailable in public runtime mode", () => {
    for (const path of ["/admin/publishing", "/workshop/rag/search", "/login", "/setup", "/api/v1/auth/me"]) {
      expect(decideRouteAccess(path, "public")).toBe("not-found");
    }
    expect(decideRouteAccess("/api/public/studies", "public")).toBe("allow");
    expect(decideRouteAccess("/studies/example", "public")).toBe("allow");
  });
});
