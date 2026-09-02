import { describe, expect, it } from "vitest";

import {
  canAccessAdmin,
  safeReturnPath,
  unauthenticatedDestination,
} from "./access";

describe("access decisions", () => {
  it("accepts only local return paths", () => {
    expect(safeReturnPath("/workshop/rag/search?query=alpha")).toBe(
      "/workshop/rag/search?query=alpha",
    );
    expect(safeReturnPath("//evil.example/path")).toBe("/workshop/workspaces");
    expect(safeReturnPath("/\\evil.example/path")).toBe("/workshop/workspaces");
    expect(safeReturnPath("/workshop/workspaces\n/redirect")).toBe(
      "/workshop/workspaces",
    );
    expect(safeReturnPath("https://evil.example/path")).toBe(
      "/workshop/workspaces",
    );
    expect(safeReturnPath(null)).toBe("/workshop/workspaces");
  });

  it("routes unauthenticated users according to setup state", () => {
    expect(unauthenticatedDestination(true, "/workshop/rag/search")).toBe(
      "/setup?next=%2Fworkshop%2Frag%2Fsearch",
    );
    expect(unauthenticatedDestination(false, "/workshop/rag/search")).toBe(
      "/login?next=%2Fworkshop%2Frag%2Fsearch",
    );
  });

  it("reserves administration for owners", () => {
    expect(canAccessAdmin({ role: "owner" })).toBe(true);
    expect(canAccessAdmin({ role: "member" })).toBe(false);
  });
});
