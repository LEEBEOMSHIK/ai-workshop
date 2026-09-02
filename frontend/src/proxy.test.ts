import { config } from "./proxy";

describe("route proxy boundary", () => {
  it("captures return paths only for protected areas", () => {
    expect(config.matcher).toEqual(["/workshop/:path*", "/admin/:path*"]);
  });
});
