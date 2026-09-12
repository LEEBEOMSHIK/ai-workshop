import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";
import { AdminNavigation } from "./AdminNavigation";
import { WorkspaceNavigation } from "./WorkspaceNavigation";

const location = vi.hoisted(() => ({ pathname: "/workshop/workspaces" as string | null }));
vi.mock("next/navigation", () => ({ usePathname: () => location.pathname }));
const owner = { id: "owner", display_name: "Owner", email: "owner@example.test", role: "owner" as const };
beforeEach(() => { location.pathname = "/workshop/workspaces"; });
afterEach(() => vi.unstubAllGlobals());

function mockLogoutBoundary() {
  const replace = vi.fn();
  const fetch = vi.fn<typeof globalThis.fetch>();
  vi.stubGlobal("fetch", fetch);
  vi.stubGlobal("window", new Proxy(window, {
    get(target, key) {
      return key === "location" ? { replace } : Reflect.get(target, key);
    },
  }));
  return { fetch, replace };
}

it.each([
  ["workspace", WorkspaceNavigation],
  ["admin", AdminNavigation],
] as const)("logs out from %s before replacing the full page with login", async (_area, Navigation) => {
  const { fetch, replace } = mockLogoutBoundary();
  let complete!: (response: Response) => void;
  fetch.mockReturnValue(new Promise((resolve) => { complete = resolve; }));
  const user = userEvent.setup();
  render(<Navigation user={owner} />);

  await user.click(screen.getByRole("button", { name: "로그아웃" }));
  const pending = screen.getByRole("button", { name: "로그아웃 중…" });
  expect(pending).toBeDisabled();
  expect(pending).toHaveAttribute("aria-busy", "true");
  expect(replace).not.toHaveBeenCalled();
  await user.click(pending);
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(fetch).toHaveBeenCalledWith("/api/v1/auth/logout", { method: "POST", credentials: "include" });

  await act(async () => complete(new Response(null, { status: 204 })));
  expect(replace).toHaveBeenCalledExactlyOnceWith("/login");
  expect(pending).toBeDisabled();
});

it.each(["http", "network"])("keeps the user on the current page after %s failure and allows retry", async (failure) => {
  const { fetch, replace } = mockLogoutBoundary();
  if (failure === "http") fetch.mockResolvedValueOnce(new Response(null, { status: 500 }));
  else fetch.mockRejectedValueOnce(new TypeError("Network unavailable"));
  const user = userEvent.setup();
  render(<WorkspaceNavigation user={{ ...owner, role: "member" }} />);
  await user.click(screen.getByRole("button", { name: "로그아웃" }));

  expect(screen.getByRole("alert")).toHaveTextContent(/로그아웃.*다시/);
  expect(screen.getByText("Owner")).toBeVisible();
  expect(replace).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "로그아웃" })).toBeEnabled();
  fetch.mockResolvedValueOnce(new Response(null, { status: 204 }));
  await user.click(screen.getByRole("button", { name: "로그아웃" }));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(replace).toHaveBeenCalledExactlyOnceWith("/login");
});

it("separates fixed area links from the current workspace menu", () => {
  render(<WorkspaceNavigation user={owner} />);
  const areas = screen.getByRole("navigation", { name: "영역 이동" });
  expect(within(areas).getAllByRole("link").map((link) => link.textContent)).toEqual(["AI Lab", "비공개 작업소", "관리자"]);
  expect(within(areas).getByRole("link", { name: "AI Lab" })).toHaveAttribute("href", "/labs");
  expect(within(areas).getByRole("link", { name: "비공개 작업소" })).toHaveAttribute("aria-current", "location");
  expect(within(screen.getByRole("navigation", { name: "비공개 작업소" })).getAllByRole("link").map((link) => link.textContent)).toEqual(["파일함", "RAG 대화", "학습 기록"]);
});

it("keeps only administration menus in the lower row with exact page selection", () => {
  location.pathname = "/admin/rag/models";
  render(<AdminNavigation user={owner} />);
  expect(screen.getByRole("link", { name: "관리자" })).toHaveAttribute("aria-current", "location");
  expect(screen.getByRole("link", { name: "RAG 모델" })).toHaveAttribute("aria-current", "page");
  expect(within(screen.getByRole("navigation", { name: "관리자 운영" })).getAllByRole("link")).toHaveLength(6);
  expect(screen.getByRole("link", { name: "권한 관리" })).toHaveAttribute("href", "/admin/system/access");
  expect(screen.queryByRole("link", { name: "파일함" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "AI Workshop" })).toBeVisible();
});

it("labels only the stored owner role as 마스터 without changing member labels", () => {
  const { rerender } = render(<AdminNavigation user={owner} />);
  expect(screen.getByText("마스터")).toBeVisible();

  rerender(<WorkspaceNavigation user={{ ...owner, role: "member" }} />);
  expect(screen.queryByText("마스터")).not.toBeInTheDocument();
  expect(screen.getByText("Owner")).toBeVisible();
});

it.each([
  ["/workshop/workspaces/w/documents", "파일함"],
  ["/workshop/learning/record", "학습 기록"],
  ["/workshop/rag/search", "RAG 대화"],
  ["/workshop/rag/domains/asset-management/chat", "RAG 대화"],
  ["/workshop/rag/domains/encoded%20slug/chat/", "RAG 대화"],
  ["/workshop/rag/sources/revision", "RAG 대화"],
])("keeps the correct current menu for deep route %s", (pathname, menu) => {
  location.pathname = pathname;
  render(<WorkspaceNavigation user={owner} />);
  expect(screen.getByRole("link", { name: menu })).toHaveAttribute("aria-current", "page");
  expect(screen.getAllByRole("link").filter((link) => link.getAttribute("aria-current") === "page")).toHaveLength(1);
});

it.each(["/workshop/workspaces-other", "/workshop/learning-other", "/workshop/rag/search-other", "/workshop/rag/sources-other/revision", "/workshop/rag/domains/example/chat-other", "/unknown", null])("does not claim a current page for unrelated path %s", (pathname) => {
  location.pathname = pathname;
  render(<WorkspaceNavigation user={owner} />);
  expect(screen.getAllByRole("link").filter((link) => link.getAttribute("aria-current") === "page")).toHaveLength(0);
});

it("updates current menu on client navigation and hides owner areas from members", () => {
  const { rerender } = render(<WorkspaceNavigation user={{ ...owner, role: "member" }} />);
  expect(screen.queryByRole("link", { name: "관리자" })).not.toBeInTheDocument();
  expect(screen.getByRole("link", { name: "파일함" })).toHaveAttribute("aria-current", "page");
  location.pathname = "/workshop/learning/record";
  rerender(<WorkspaceNavigation user={{ ...owner, role: "member" }} />);
  expect(screen.getByRole("link", { name: "파일함" })).not.toHaveAttribute("aria-current");
  expect(screen.getByRole("link", { name: "학습 기록" })).toHaveAttribute("aria-current", "page");
});

it.each(["/workshop-other/workspaces", "/admin-other/rag/models", "/labs-other", "/admin/rag/models-other"])("does not highlight a misleading area or administration menu for %s", (pathname) => {
  location.pathname = pathname;
  render(<AdminNavigation user={owner} />);
  expect(screen.getAllByRole("link").filter((link) => link.getAttribute("aria-current") === "page")).toHaveLength(0);
  if (!pathname.startsWith("/admin/")) {
    expect(screen.getAllByRole("link").filter((link) => link.hasAttribute("aria-current"))).toHaveLength(0);
  }
});

it("keeps area and current-menu links reachable in normal keyboard order", async () => {
  const user = userEvent.setup();
  render(<WorkspaceNavigation user={owner} />);
  await user.tab();
  expect(screen.getByRole("link", { name: "AI Workshop" })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("link", { name: "AI Lab" })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("link", { name: "비공개 작업소" })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("link", { name: "관리자" })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("button", { name: "로그아웃" })).toHaveFocus();
  await user.tab();
  expect(screen.getByRole("link", { name: "파일함" })).toHaveFocus();
});
