import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "./client";
import { serverApiRequest } from "./server-client";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("serverApiRequest", () => {
  it("calls FastAPI directly while forwarding the session cookie without caching", async () => {
    vi.stubEnv("API_PORT", "18000");
    let captured: [RequestInfo | URL, RequestInit | undefined] | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        captured = [input, init];
        return new Response(JSON.stringify({ id: "owner-1" }), { status: 200 });
      }),
    );

    const response = await serverApiRequest<{ id: string }>(
      "/api/v1/auth/me",
      {},
      "ai_workshop_session=token",
    );

    expect(response).toEqual({ id: "owner-1" });
    expect(captured?.[0]).toBe("http://127.0.0.1:18000/api/v1/auth/me");
    expect(captured?.[1]?.cache).toBe("no-store");
    expect(new Headers(captured?.[1]?.headers).get("cookie")).toBe(
      "ai_workshop_session=token",
    );
  });

  it("preserves typed FastAPI errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "owner_required",
              message: "Owner access is required.",
              correlation_id: "correlation-403",
            },
          }),
          { status: 403 },
        ),
      ),
    );

    await expect(serverApiRequest("/api/v1/admin/rag/models")).rejects.toEqual(
      new ApiError(
        "Owner access is required.",
        403,
        "owner_required",
        "correlation-403",
      ),
    );
  });
});
