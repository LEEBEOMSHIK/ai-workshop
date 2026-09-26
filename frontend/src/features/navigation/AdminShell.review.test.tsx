import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AdminShell } from "./AdminShell";
import AdminLayout from "../../app/(administration)/admin/layout";
import { requireOwner } from "../../shared/auth/server-session";
import { ApiError } from "../../shared/api/client";

const route = vi.hoisted(() => ({ pathname: "/admin/system/issues" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.pathname, useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("next/headers", () => ({ headers: async () => new Headers({"x-ai-workshop-return-to": "/admin/system/issues?issue=RAG-0001"}) }));
vi.mock("../../shared/auth/server-session", () => ({ requireOwner: vi.fn() }));

const owner = { id: "review-owner", display_name: "Owner", email: "owner@example.test", role: "owner" as const };
let mobile = true;
const listeners = new Set<() => void>();

beforeEach(() => {
  route.pathname = "/admin/system/issues";
  mobile = true;
  listeners.clear();
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    get matches() { return mobile; },
    media: "(max-width: 63.999rem)", onchange: null,
    addEventListener: (_name: string, callback: () => void) => listeners.add(callback),
    removeEventListener: (_name: string, callback: () => void) => listeners.delete(callback),
  })));
  if (!HTMLDialogElement.prototype.showModal) Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, writable: true, value() {} });
  if (!HTMLDialogElement.prototype.close) Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, writable: true, value() {} });
  vi.spyOn(HTMLDialogElement.prototype, "showModal").mockImplementation(function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  });
  vi.spyOn(HTMLDialogElement.prototype, "close").mockImplementation(function (this: HTMLDialogElement) {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  });
});

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("removes all administrator navigation for a non-owner", () => {
  render(<AdminShell user={{ ...owner, role: "member" }}><main>Protected placeholder</main></AdminShell>);
  expect(screen.queryByRole("button", { name: "메뉴 열기" })).not.toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "관리자 운영" })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: "문제·개선 이력" })).not.toBeInTheDocument();
});

it("the server layout withholds page content when owner authorization fails", async () => {
  vi.mocked(requireOwner).mockRejectedValueOnce(new ApiError("Forbidden", 403, "owner_required"));
  render(await AdminLayout({children: <main>Protected issue content</main>}));
  expect(requireOwner).toHaveBeenCalledWith("/admin/system/issues?issue=RAG-0001");
  expect(screen.queryByText("Protected issue content")).not.toBeInTheDocument();
  expect(screen.queryByRole("navigation", { name: "관리자 운영" })).not.toBeInTheDocument();
});

it("closes the drawer on route changes and returns focus to its trigger", async () => {
  const user = userEvent.setup();
  const { rerender } = render(<AdminShell user={owner}><main>Content</main></AdminShell>);
  const trigger = screen.getByRole("button", { name: "메뉴 열기" });
  await user.click(trigger);
  expect(screen.getByRole("dialog", { name: "관리자 메뉴" })).toHaveAttribute("open");
  route.pathname = "/admin/rag/models";
  rerender(<AdminShell user={owner}><main>Changed</main></AdminShell>);
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "관리자 메뉴" })).not.toBeInTheDocument());
  expect(trigger).toHaveFocus();
});

it("closes a mobile drawer when switching to desktop and keeps all seven links", async () => {
  const user = userEvent.setup();
  render(<AdminShell user={owner}><main>Content</main></AdminShell>);
  await user.click(screen.getByRole("button", { name: "메뉴 열기" }));
  act(() => { mobile = false; listeners.forEach(listener => listener()); });
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "관리자 메뉴" })).not.toBeInTheDocument());
  const navigation = screen.getByRole("navigation", { name: "관리자 운영" });
  expect(within(navigation).getAllByRole("link")).toHaveLength(7);
  expect(document.body.style.overflow).not.toBe("hidden");
});

it("returns focus after the native dialog close event", async () => {
  const user = userEvent.setup();
  render(<AdminShell user={owner}><main>Content</main></AdminShell>);
  const trigger = screen.getByRole("button", { name: "메뉴 열기" });
  await user.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "관리자 메뉴" });
  dialog.removeAttribute("open");
  fireEvent(dialog, new Event("close"));
  await waitFor(() => expect(trigger).toHaveFocus());
});

it("reopens the new current group while preserving unrelated collapsed groups", () => {
  mobile = false;
  const { rerender } = render(<AdminShell user={owner}/>);
  const navigation = screen.getByRole("navigation", { name: "관리자 운영" });
  const ragGroup = within(navigation).getByText("RAG 관리").closest("details")!;
  const publicGroup = within(navigation).getByText("공개 콘텐츠").closest("details")!;
  ragGroup.open = false;
  publicGroup.open = false;
  route.pathname = "/admin/rag/configurations/nested";
  rerender(<AdminShell user={owner}/>);
  expect(ragGroup.open).toBe(true);
  expect(publicGroup.open).toBe(false);
  expect(within(navigation).getByRole("link", { name: /구성/ })).toHaveAttribute("aria-current", "page");
});

it("the focus boundary excludes collapsed group links and hidden footer controls", async () => {
  const user = userEvent.setup();
  render(<AdminShell user={owner}/>);
  await user.click(screen.getByRole("button", { name: "메뉴 열기" }));
  const dialog = screen.getByRole("dialog", { name: "관리자 메뉴" });
  dialog.querySelectorAll("details").forEach(group => { group.open = false; });
  within(dialog).getByRole("navigation", { name: "영역 이동" }).hidden = true;
  within(dialog).getByRole("button", { name: "로그아웃" }).parentElement!.hidden = true;
  const first = within(dialog).getByRole("link", { name: "AI Workshop" });
  const last = within(dialog).getByText("시스템 관리");
  first.focus();
  await user.tab({shift: true});
  expect(last).toHaveFocus();
  await user.tab();
  expect(first).toHaveFocus();
});
