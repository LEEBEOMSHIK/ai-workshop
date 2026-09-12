import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { serverApiRequest } from "../../../../shared/api/server-client";
import { incomingCookieHeader, requireWorkspaceUser } from "../../../../shared/auth/server-session";
import WorkspacesRoute from "./page";

vi.mock("../../../../shared/api/server-client", () => ({ serverApiRequest: vi.fn() }));
vi.mock("../../../../shared/auth/server-session", () => ({ incomingCookieHeader: vi.fn(), requireWorkspaceUser: vi.fn() }));
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(incomingCookieHeader).mockResolvedValue("synthetic-session");
  vi.mocked(serverApiRequest).mockResolvedValue([]);
});
afterEach(() => vi.unstubAllGlobals());

it("shows company creation only to the current authenticated owner and submits the existing contract", async () => {
  vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "owner", role: "owner", display_name: "Synthetic owner", email: "owner@example.test" });
  const fetcher = vi.fn<typeof fetch>(async () => Response.json({ id: "company-id", kind: "company", name: "Company", expires_at: null }, { status: 201 }));
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(await WorkspacesRoute());
  expect(requireWorkspaceUser).toHaveBeenCalledWith("/workshop/workspaces");
  expect(serverApiRequest).toHaveBeenCalledWith("/api/v1/workspaces", {}, "synthetic-session");
  await user.click(screen.getByRole("button", { name: "공간 만들기" }));
  await user.selectOptions(screen.getByRole("combobox", { name: "새 공간 유형" }), "company");
  await user.type(screen.getByRole("textbox", { name: "공간 이름" }), "Company");
  expect(screen.queryByLabelText("만료 일시")).not.toBeInTheDocument();
  expect(fetcher).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "공간 만들기" }));
  expect(await screen.findByRole("link", { name: /Company/ })).toHaveAttribute("href", "/workshop/workspaces/company-id/documents");
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toEqual({ name: "Company", kind: "company", expires_at: null });
});

it("does not expose company or unsupported team creation to a member", async () => {
  vi.mocked(requireWorkspaceUser).mockResolvedValue({ id: "member", role: "member", display_name: "Synthetic member", email: "member@example.test" });
  const user = userEvent.setup();
  render(await WorkspacesRoute());
  expect(screen.queryByRole("form", { name: "새 지식 공간 만들기" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "공간 만들기" }));
  expect(screen.queryByRole("option", { name: "전사" })).not.toBeInTheDocument();
  expect(screen.queryByRole("option", { name: "팀" })).not.toBeInTheDocument();
  expect(screen.getByRole("option", { name: "개인" })).toBeInTheDocument();
  expect(screen.getByRole("option", { name: "임시" })).toBeInTheDocument();
});
