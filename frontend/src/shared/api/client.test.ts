import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiRequest } from "./client";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("apiRequest", () => {
  it("includes cookies and serializes JSON request bodies", async () => {
    let captured: [RequestInfo | URL, RequestInit | undefined] | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        captured = [input, init];
        return new Response(JSON.stringify({ id: "user-1" }), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }),
    );

    const result = await apiRequest<{ id: string }>("/api/v1/example", {
      method: "POST",
      json: { name: "workshop" },
    });

    expect(result).toEqual({ id: "user-1" });
    expect(captured).toEqual([
      "/api/v1/example",
      {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name: "workshop" }),
      },
    ]);
  });

  it("preserves multipart boundaries by leaving content-type unset", async () => {
    let capturedInit: RequestInit | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
        capturedInit = init;
        return new Response(JSON.stringify({ id: "document-1" }), { status: 201 });
      }),
    );
    const form = new FormData();
    form.append("file", new File(["sample"], "sample.pdf"));

    await apiRequest("/api/v1/example", { method: "POST", body: form });

    expect(capturedInit?.body).toBe(form);
    expect(capturedInit?.headers).toBeUndefined();
    expect(capturedInit?.credentials).toBe("include");
  });

  it("throws a typed error with the server correlation id", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "invalid_profile",
              message: "Profile is invalid.",
              correlation_id: "correlation-123",
            },
          }),
          { status: 422, headers: { "content-type": "application/json" } },
        ),
      ),
    );

    const request = apiRequest("/api/v1/example");

    await expect(request).rejects.toEqual(
      new ApiError("Profile is invalid.", 422, "invalid_profile", "correlation-123"),
    );
  });

  it("keeps the typed fallback when an upstream returns malformed error JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("{}", { status: 502 })),
    );

    await expect(apiRequest("/api/v1/example")).rejects.toEqual(
      new ApiError("요청을 완료하지 못했습니다.", 502, "request_failed"),
    );
  });
});
