import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import FlowsRoute from "./page";
import { requireWorkspaceUser } from "../../../../shared/auth/server-session";

vi.mock("../../../../shared/auth/server-session", () => ({ requireWorkspaceUser: vi.fn() }));
afterEach(() => { cleanup(); vi.resetAllMocks(); });

it("renders the default answer flow for an authenticated member without admin links", async () => {
  vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "flow-member", email: "member@example.test", display_name: "Member", role: "member" });
  render(await FlowsRoute());
  expect(screen.getByRole("heading", { name: "흐름도", level: 1 })).toBeVisible();
  expect(screen.getByRole("heading", { name: "검색·답변 생성", level: 2 })).toBeVisible();
  expect(screen.queryByRole("link", { name: /실행 모니터링/ })).not.toBeInTheDocument();
});

it("does not render private flow data when the server authentication redirects", async () => {
  vi.mocked(requireWorkspaceUser).mockRejectedValue(new Error("NEXT_REDIRECT"));
  await expect(FlowsRoute()).rejects.toThrow("NEXT_REDIRECT");
  expect(screen.queryByRole("heading", { name: "흐름도" })).not.toBeInTheDocument();
});
