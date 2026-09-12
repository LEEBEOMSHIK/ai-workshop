import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import LearningDetailRoute from "./page";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("passes the dynamic record id to the real detail feature", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/v1/learning/records/record%2Fid") return jsonResponse(record());
    if (path === "/api/v1/learning/topics" || path === "/api/v1/rag/evaluation-runs?limit=20") return jsonResponse([]);
    return jsonResponse({ items: [], next_cursor: null });
  }));

  render(await LearningDetailRoute({ params: Promise.resolve({ recordId: "record/id" }) }));

  expect(await screen.findByRole("heading", { name: "경로 기록", level: 1 })).toBeVisible();
  expect(fetch).toHaveBeenCalledWith(
    "/api/v1/learning/records/record%2Fid",
    expect.objectContaining({ credentials: "include" }),
  );
});

function record() {
  return { id: "record/id", revision: 1, created_at: "2026-09-07T01:02:03Z", updated_at: "2026-09-07T01:02:03Z", archived_at: null, draft: { title: "경로 기록", body: "본문", kind: "note", topic_keys: [], domain_labels: [], experiment: null, references: [] }, reference_views: [], dataset_reference_view: null, unavailable_reference_count: 0 };
}

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), { status: 200, headers: { "content-type": "application/json" } });
}
