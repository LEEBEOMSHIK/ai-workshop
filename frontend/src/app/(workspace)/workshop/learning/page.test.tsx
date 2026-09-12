import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import LearningRoute from "./page";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("renders the real learning list feature at the protected workspace route", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path === "/api/v1/learning/topics" || path === "/api/v1/rag/evaluation-runs?limit=20") {
      return jsonResponse([]);
    }
    return jsonResponse({ items: [], next_cursor: null });
  }));

  render(<LearningRoute />);

  expect(await screen.findByRole("heading", { name: "학습 기록", level: 1 })).toBeVisible();
  expect(screen.getByRole("button", { name: "새 메모" })).toBeEnabled();
});

function jsonResponse(value: unknown): Response {
  return new Response(JSON.stringify(value), { status: 200, headers: { "content-type": "application/json" } });
}
