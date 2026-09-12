import { afterEach, expect, it, vi } from "vitest";

import { ApiError } from "../../shared/api/client";
import { getPublicStudy, listPublicStudyCatalog, publishingAdminApi } from "./api";
import { adminStudy, studySnapshot } from "./test-fixtures";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

it("requests a no-cache catalog page from the public reader with a topic filter", async () => {
  vi.stubEnv("AI_WORKSHOP_PUBLIC_API_TARGET", "http://127.0.0.1:18001");
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ items: [], total: 0, page: 1, page_size: 12, total_pages: 0, topics: [] })));
  vi.stubGlobal("fetch", fetcher);
  await expect(listPublicStudyCatalog({ page: 2, topic: "rag" })).resolves.toMatchObject({ total: 0 });
  expect(fetcher).toHaveBeenCalledWith("http://127.0.0.1:18001/api/public/study-catalog?page=2&topic_key=rag", expect.objectContaining({ cache: "no-store" }));
});

it("sends JSON and the publishing mutation marker while retaining the caller request id", async () => {
  let captured: [RequestInfo | URL, RequestInit | undefined] | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    captured = [input, init];
    return new Response(JSON.stringify(adminStudy()), { status: 200 });
  }));

  await publishingAdminApi.publish("hybrid-search", {
    expected_revision: 3,
    expected_digest: "a".repeat(64),
    request_id: "same-request-id",
  });

  const headers = new Headers(captured?.[1]?.headers);
  expect(headers.get("content-type")).toBe("application/json");
  expect(headers.get("x-publishing-request")).toBe("1");
  expect(JSON.parse(String(captured?.[1]?.body))).toEqual({
    expected_revision: 3,
    expected_digest: "a".repeat(64),
    request_id: "same-request-id",
  });
});

it("observes a withdrawn public detail as the same safe not-found response on a fresh read", async () => {
  vi.stubEnv("AI_WORKSHOP_PUBLIC_API_TARGET", "http://127.0.0.1:18001");
  vi.stubGlobal("fetch", vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(studySnapshot()), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ error: {
      code: "not_found",
      message: "Resource not found.",
      correlation_id: "public-correlation",
    } }), { status: 404 })));

  await expect(getPublicStudy("hybrid-search")).resolves.toEqual(studySnapshot());
  await expect(getPublicStudy("hybrid-search")).rejects.toEqual(
    new ApiError("Resource not found.", 404, "not_found", "public-correlation"),
  );
});
