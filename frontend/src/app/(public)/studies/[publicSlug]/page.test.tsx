import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import PublicStudyRoute from "./page";
import { studySnapshot } from "../../../../features/publishing/test-fixtures";

afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

it("preserves only validated list context in the return action", async () => {
  vi.stubEnv("AI_WORKSHOP_PUBLIC_API_TARGET", "http://127.0.0.1:18001");
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(studySnapshot()))));
  render(await PublicStudyRoute({ params: Promise.resolve({ publicSlug: "hybrid-search" }), searchParams: Promise.resolve({ page: "2", topic: "rag", returnUrl: "https://evil.test" }) }));
  expect(screen.getByRole("link", { name: "공개 연구 기록으로 돌아가기" })).toHaveAttribute("href", "/labs/rag/studies?topic=rag&page=2");
});

it("uses the default list for a standalone detail URL", async () => {
  vi.stubEnv("AI_WORKSHOP_PUBLIC_API_TARGET", "http://127.0.0.1:18001");
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(studySnapshot()))));
  render(await PublicStudyRoute({ params: Promise.resolve({ publicSlug: "hybrid-search" }) }));
  expect(screen.getByRole("link", { name: "공개 연구 기록으로 돌아가기" })).toHaveAttribute("href", "/labs/rag/studies");
});
