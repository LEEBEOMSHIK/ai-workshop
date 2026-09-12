import { afterEach, expect, it, vi } from "vitest";

import { publicApiRequest } from "./public-client";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it("reads the public store without credentials or caching", async () => {
  vi.stubEnv("AI_WORKSHOP_PUBLIC_API_TARGET", "http://127.0.0.1:18001");
  let captured: [RequestInfo | URL, RequestInit | undefined] | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    captured = [input, init];
    return new Response(JSON.stringify({ items: [] }), { status: 200 });
  }));

  await publicApiRequest("/api/public/studies");

  expect(captured?.[0]).toBe("http://127.0.0.1:18001/api/public/studies");
  expect(captured?.[1]).toMatchObject({ credentials: "omit", cache: "no-store" });
});
