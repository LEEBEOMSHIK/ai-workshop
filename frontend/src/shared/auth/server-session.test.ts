import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import { serverApiRequest } from "../api/server-client";
import {
  requireOwner,
  resolveSession,
  type SessionApiRequest,
} from "./server-session";

vi.mock("next/headers", () => ({ cookies: vi.fn() }));
vi.mock("next/navigation", () => ({ redirect: vi.fn() }));
vi.mock("../api/server-client", () => ({ serverApiRequest: vi.fn() }));

const owner = {
  id: "6806a6c1-04c4-4f2c-87d8-8cd1bf06e898",
  display_name: "Owner",
  email: "owner@example.com",
  role: "owner" as const,
};

describe("resolveSession", () => {
  it("returns the FastAPI user and forwards the incoming cookie", async () => {
    const request = vi.fn<SessionApiRequest>().mockResolvedValue(owner);

    const decision = await resolveSession(
      "ai_workshop_session=token",
      "/app/workspaces",
      request,
    );

    expect(decision).toEqual({ kind: "authenticated", user: owner });
    expect(request).toHaveBeenCalledWith(
      "/api/v1/auth/me",
      {},
      "ai_workshop_session=token",
    );
  });

  it.each([
    [true, "/setup?next=%2Fapp%2Frag%2Fsearch"],
    [false, "/login?next=%2Fapp%2Frag%2Fsearch"],
  ])("maps a 401 using setup_required=%s", async (setupRequired, destination) => {
    const request = vi.fn<SessionApiRequest>(async (path) => {
      if (path === "/api/v1/auth/me") {
        throw new ApiError("Authentication is required.", 401, "not_authenticated");
      }
      return { setup_required: setupRequired };
    });

    const decision = await resolveSession("", "/app/rag/search", request);

    expect(decision).toEqual({ kind: "redirect", destination });
  });

  it("does not disguise a FastAPI outage as an authentication redirect", async () => {
    const unavailable = new ApiError("Upstream unavailable.", 503, "request_failed");
    const request = vi.fn<SessionApiRequest>().mockRejectedValue(unavailable);

    await expect(resolveSession("", "/app/workspaces", request)).rejects.toBe(
      unavailable,
    );
  });
});

describe("requireOwner", () => {
  it("returns a member to the canonical private workshop with an error", async () => {
    vi.mocked(cookies).mockResolvedValue({
      getAll: () => [{ name: "ai_workshop_session", value: "token" }],
    } as Awaited<ReturnType<typeof cookies>>);
    vi.mocked(serverApiRequest).mockResolvedValue({
      id: "10000000-0000-0000-0000-000000000002",
      display_name: "Member",
      email: "member@example.test",
      role: "member",
    });

    await requireOwner("/admin/rag/configurations");

    expect(redirect).toHaveBeenCalledWith(
      "/workshop/workspaces?error=owner_required",
    );
  });
});
