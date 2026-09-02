import { describe, expect, it } from "vitest";

import {
  canAccessAdmin,
  safeReturnPath,
  unauthenticatedDestination,
} from "./access";

describe("access decisions", () => {
  it("accepts only local return paths", () => {
    expect(safeReturnPath("/app/rag/search?query=alpha")).toBe(
      "/app/rag/search?query=alpha",
    );
    expect(safeReturnPath("//evil.example/path")).toBe("/app/workspaces");
    expect(safeReturnPath("/\\evil.example/path")).toBe("/app/workspaces");
    expect(safeReturnPath("/app/workspaces\n/redirect")).toBe("/app/workspaces");
    expect(safeReturnPath("https://evil.example/path")).toBe("/app/workspaces");
    expect(safeReturnPath(null)).toBe("/app/workspaces");
  });

  it("routes unauthenticated users according to setup state", () => {
    expect(unauthenticatedDestination(true, "/app/rag/search")).toBe(
      "/setup?next=%2Fapp%2Frag%2Fsearch",
    );
    expect(unauthenticatedDestination(false, "/app/rag/search")).toBe(
      "/login?next=%2Fapp%2Frag%2Fsearch",
    );
  });

  it("reserves administration for owners", () => {
    expect(canAccessAdmin({ role: "owner" })).toBe(true);
    expect(canAccessAdmin({ role: "member" })).toBe(false);
  });
});
