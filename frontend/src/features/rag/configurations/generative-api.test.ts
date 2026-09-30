import { afterEach, expect, it, vi } from "vitest";
import { retryGenerativeRun } from "./generative-api";

afterEach(() => vi.unstubAllGlobals());

it("sends a JSON mutation request when retrying a generative evaluation", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => new Response("{}", {
    headers: { "content-type": "application/json" },
  }));
  vi.stubGlobal("fetch", fetcher);

  await retryGenerativeRun("run-id");

  expect(fetcher).toHaveBeenCalledTimes(1);
  const [path, request] = fetcher.mock.calls[0];
  expect(path).toBe("/api/v1/rag/generative-evaluations/run-id/retry");
  expect(request?.method).toBe("POST");
  expect(request?.credentials).toBe("include");
  const headers = new Headers(request?.headers);
  expect(headers.get("x-codex-request")).toBe("1");
  expect(headers.get("content-type")).toBe("application/json");
  expect(request?.body).toBe("{}");
});
