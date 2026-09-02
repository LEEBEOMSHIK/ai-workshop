import { describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import {
  resolveSession,
  type SessionApiRequest,
} from "./server-session";

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
