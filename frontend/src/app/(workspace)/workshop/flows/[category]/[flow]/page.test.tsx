import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import FlowRoute from "./page";
import { requireWorkspaceUser } from "../../../../../../shared/auth/server-session";
import FlowNotFound from "../../not-found";

vi.mock("../../../../../../shared/auth/server-session", () => ({ requireWorkspaceUser: vi.fn() }));
vi.mock("next/navigation", () => ({ notFound: () => { throw new Error("NEXT_NOT_FOUND"); } }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("renders the exact requested flow with owner-only related links", async () => {
  vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "flow-owner", email: "owner@example.test", display_name: "Owner", role: "owner" });
  render(await FlowRoute({ params: Promise.resolve({ category: "rag", flow: "multiturn" }) }));
  expect(screen.getByRole("heading", { name: "멀티턴 문맥 관리", level: 2 })).toBeVisible();
  expect(screen.getByRole("link", { name: /실행 모니터링/ })).toHaveAttribute("href", "/admin/rag/executions");
  expect(screen.getByRole("link", { name: "멀티턴 문맥 관리" })).toHaveAttribute("aria-current", "page");
});

it.each([{ category: "common", flow: "sessions" }, { category: "rag", flow: "absent" }])("returns not-found for an unknown exact pair: %s", async (params) => {
  vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "flow-member", email: "member@example.test", display_name: "Member", role: "member" });
  await expect(FlowRoute({ params: Promise.resolve(params) })).rejects.toThrow("NEXT_NOT_FOUND");
});

it("offers a canonical list return from the not-found state", () => {
  render(<FlowNotFound />);
  expect(screen.getByRole("heading", { name: "흐름도를 찾을 수 없습니다" })).toBeVisible();
  expect(screen.getByRole("link", { name: "흐름도 목록으로" })).toHaveAttribute("href", "/workshop/flows");
});
