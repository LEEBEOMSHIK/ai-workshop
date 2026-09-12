import { cookies } from "next/headers";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LoginPage } from "../../../features/identity/LoginPage";
import { ServerRouteFailure } from "../../../shared/ui/ServerRouteFailure";
import LoginRoute from "./page";

vi.mock("next/headers", () => ({ cookies: vi.fn() }));

const owner = {
  id: "6806a6c1-04c4-4f2c-87d8-8cd1bf06e898",
  display_name: "Owner",
  email: "owner@example.com",
  role: "owner",
};

function stubBackend(sessionStatus = 200, setupRequired = false) {
  const fetcher = vi.fn(async (input: string | URL | Request) => {
    const path = new URL(String(input)).pathname;
    if (path === "/api/v1/auth/me") {
      return Response.json(sessionStatus === 200 ? owner : {
        error: { code: "session_failure", message: "Session failed", correlation_id: "test-ref" },
      }, { status: sessionStatus });
    }
    if (path === "/api/v1/setup/status") {
      return Response.json({ setup_required: setupRequired });
    }
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return fetcher;
}

function route(next?: string | string[]) {
  return LoginRoute({ searchParams: Promise.resolve({ next }) });
}

beforeEach(() => {
  vi.stubEnv("AI_WORKSHOP_FRONTEND_RUNTIME", "private");
  vi.mocked(cookies).mockResolvedValue({
    getAll: () => [{ name: "session", value: "synthetic-session" }],
  } as Awaited<ReturnType<typeof cookies>>);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
  vi.clearAllMocks();
});

describe("LoginRoute", () => {
  it("redirects an existing session to the protected destination and forwards cookies", async () => {
    const fetcher = stubBackend();
    await expect(route("/workshop/rag/search?query=alpha#results")).rejects.toMatchObject({
      digest: "NEXT_REDIRECT;replace;/workshop/rag/search?query=alpha#results;307;",
    });
    expect(fetcher).toHaveBeenCalledWith(expect.stringContaining("/api/v1/auth/me"), expect.objectContaining({
      cache: "no-store",
      headers: expect.any(Headers),
    }));
    const init = fetcher.mock.calls[0] as unknown as [string, RequestInit];
    expect(new Headers(init[1].headers).get("cookie")).toBe("session=synthetic-session");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it.each([
    undefined, ["/admin/system/access"], "https://example.com", "//example.com", "/\\example.com",
    "/\n/evil", "/login", "/login?next=/login", "/login/#again", "/setup", "/setup/",
    "/a/../login", "/a/%2e%2e/setup", "/%6cogin", "/%73etup", "/login%2f", "/%ZZ",
  ].map((next) => ({ next })))("uses the workshop for unsafe or looping next $next", async ({ next }) => {
    stubBackend();
    await expect(route(next)).rejects.toMatchObject({
      digest: "NEXT_REDIRECT;replace;/workshop/workspaces;307;",
    });
  });

  it("keeps the login form after a 401 with setup complete", async () => {
    stubBackend(401);
    const result = await route("/admin/system/access");
    expect(result.type).toBe(LoginPage);
    expect(result.props.nextPath).toBe("/admin/system/access");
  });

  it("redirects an unauthenticated first user to setup with the protected destination", async () => {
    stubBackend(401, true);
    await expect(route("/workshop/rag/search?query=alpha")).rejects.toMatchObject({
      digest: "NEXT_REDIRECT;replace;/setup?next=%2Fworkshop%2Frag%2Fsearch%3Fquery%3Dalpha;307;",
    });
  });

  it.each([403, 500, 503])("shows session HTTP %i failures without treating them as logged out", async (status) => {
    const fetcher = stubBackend(status);
    const result = await route();
    expect(result.type).toBe(ServerRouteFailure);
    expect(result.props.failure).toEqual({ status, code: "session_failure", correlationId: "test-ref" });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("propagates network failures", async () => {
    const error = new TypeError("network unavailable");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(error));
    await expect(route()).rejects.toBe(error);
  });

  it("never calls a private backend in the public runtime", async () => {
    vi.stubEnv("AI_WORKSHOP_FRONTEND_RUNTIME", "public");
    const fetcher = stubBackend();
    await expect(route()).rejects.toThrow("private_api_unavailable_in_public_runtime");
    expect(fetcher).not.toHaveBeenCalled();
  });
});
