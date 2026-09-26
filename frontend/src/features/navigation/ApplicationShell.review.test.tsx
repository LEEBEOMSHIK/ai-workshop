import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApplicationShell } from "./ApplicationShell";

const route = vi.hoisted(() => ({ pathname: "/labs/rag/studies" }));
vi.mock("next/navigation", () => ({ usePathname: () => route.pathname }));
const owner = {id: "review-owner", display_name: "Owner", email: "owner@example.test", role: "owner" as const};
let mobile = false;
const mediaListeners = new Set<() => void>();

beforeEach(() => {
  mobile = false;
  route.pathname = "/labs/rag/studies";
  mediaListeners.clear();
  vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new Error("Unexpected navigation request"))));
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    get matches() {return mobile;},
    addEventListener: (_name: string, listener: () => void) => mediaListeners.add(listener),
    removeEventListener: (_name: string, listener: () => void) => mediaListeners.delete(listener),
  })));
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", {configurable: true, writable: true, value() {this.open = true; this.querySelector("button")?.focus();}});
  Object.defineProperty(HTMLDialogElement.prototype, "close", {configurable: true, writable: true, value() {this.open = false; this.dispatchEvent(new Event("close"));}});
});
afterEach(() => {vi.unstubAllGlobals(); document.body.style.overflow = "";});

it("public navigation never requests authentication or exposes account data even with a supplied owner", () => {
  render(<ApplicationShell area="public" user={owner}><main>Public content</main></ApplicationShell>);
  expect(screen.getByText("Public content")).toBeVisible();
  expect(screen.queryByText(owner.display_name)).not.toBeInTheDocument();
  expect(screen.queryByRole("link", {name: "관리자"})).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "로그아웃"})).not.toBeInTheDocument();
  expect(fetch).not.toHaveBeenCalled();
});

it("a member can navigate the workspace but cannot see administration links", () => {
  route.pathname = "/workshop/learning";
  render(<ApplicationShell area="workspace" user={{...owner, role: "member"}}><main>Workspace content</main></ApplicationShell>);
  expect(screen.getByText("Workspace content")).toBeVisible();
  expect(screen.getByRole("navigation", {name: "비공개 작업소"})).toBeVisible();
  expect(screen.queryByRole("link", {name: "관리자"})).not.toBeInTheDocument();
  expect(screen.queryByRole("link", {name: "권한 관리"})).not.toBeInTheDocument();
  expect(screen.queryByText("마스터")).not.toBeInTheDocument();
});

it.each(["workspace", "admin"] as const)("withholds private content without an authenticated user in %s", area => {
  render(<ApplicationShell area={area}><main>Private content</main></ApplicationShell>);
  expect(screen.queryByText("Private content")).not.toBeInTheDocument();
});

it("domain files identify only the file menu, not the conversation menu", () => {
  route.pathname = "/workshop/rag/domains/example/files";
  render(<ApplicationShell area="workspace" user={owner}/>);
  const nav = screen.getByRole("navigation", {name: "비공개 작업소"});
  const current = within(nav).getAllByRole("link").filter(link => link.getAttribute("aria-current") === "page");
  expect(current).toHaveLength(1);
  expect(current[0]).toHaveTextContent("파일함");
});

it("the most specific public route receives the sole current-page mark", () => {
  render(<ApplicationShell area="public"/>);
  const nav = screen.getByRole("navigation", {name: "공개 전시실"});
  const current = within(nav).getAllByRole("link").filter(link => link.getAttribute("aria-current") === "page");
  expect(current).toHaveLength(1);
  expect(current[0]).toHaveAttribute("href", "/labs/rag/studies");
});

it("immersive mobile content emits matching drawer signals and desktop retains the shared sidebar", async () => {
  mobile = true;
  route.pathname = "/";
  const notify = vi.fn();
  const user = userEvent.setup();
  const {unmount} = render(<ApplicationShell area="public" immersive onMenuOpenChange={notify}><canvas tabIndex={0}/></ApplicationShell>);
  const trigger = screen.getByRole("button", {name: "메뉴 열기"});
  await user.click(trigger);
  expect(screen.getByRole("dialog", {name: "공개 전시실 메뉴"})).toHaveAttribute("open");
  expect(notify).toHaveBeenLastCalledWith(true);
  await user.click(screen.getByRole("button", {name: "메뉴 닫기"}));
  expect(notify).toHaveBeenLastCalledWith(false);
  expect(trigger).toHaveFocus();
  act(() => {mobile = false; mediaListeners.forEach(listener => listener());});
  expect(screen.getByRole("navigation", {name: "공개 전시실"})).toBeVisible();
  expect(screen.queryByRole("button", {name: "메뉴 열기"})).not.toBeInTheDocument();
  unmount();
  expect(document.body.style.overflow).not.toBe("hidden");
});
