import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import PublicStudiesRoute from "./page";
import { studySnapshot } from "../../../../../features/publishing/test-fixtures";

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

it("loads the server catalog with normalized URL filters and uses the returned clamped page", async () => {
  vi.stubEnv("AI_WORKSHOP_PUBLIC_API_TARGET", "http://127.0.0.1:18001");
  const fetcher = vi.fn(async () => new Response(JSON.stringify({ items: [studySnapshot()], total: 13, page: 2, page_size: 12, total_pages: 2, topics: [{ key: "rag", count: 13 }] })));
  vi.stubGlobal("fetch", fetcher);
  render(await PublicStudiesRoute({ searchParams: Promise.resolve({ page: "99", topic: "rag", returnUrl: "https://evil.test" }) }));
  expect(fetcher).toHaveBeenCalledWith("http://127.0.0.1:18001/api/public/study-catalog?page=99&topic_key=rag", expect.anything());
  expect(screen.getByRole("link", { name: "하이브리드 검색 실험 읽기" })).toHaveAttribute("href", "/studies/hybrid-search?topic=rag&page=2");
});

it("normalizes invalid query values and distinguishes a failed reader", async () => {
  vi.stubEnv("AI_WORKSHOP_PUBLIC_API_TARGET", "http://127.0.0.1:18001");
  const fetcher = vi.fn(async () => new Response("{}", { status: 503 }));
  vi.stubGlobal("fetch", fetcher);
  render(await PublicStudiesRoute({ searchParams: Promise.resolve({ page: "-2", topic: "https://evil.test" }) }));
  expect(fetcher).toHaveBeenCalledWith("http://127.0.0.1:18001/api/public/study-catalog?page=1", expect.anything());
  expect(screen.getByRole("alert")).toBeVisible();
  expect(screen.queryByText(/총 .*개 기록/)).not.toBeInTheDocument();
});
