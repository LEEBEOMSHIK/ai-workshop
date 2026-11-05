import { act, fireEvent, render, screen, within } from "@testing-library/react";
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

it("keeps the conversation draft mounted when opening and closing workspace navigation", async () => {
  route.pathname = "/workshop/rag/domains/example/chat";
  const user = userEvent.setup();
  render(<ApplicationShell area="workspace" user={{...owner, role: "member"}}>
    <textarea aria-label="질문" />
  </ApplicationShell>);
  const draft = screen.getByRole("textbox", {name: "질문"});
  await user.type(draft, "작성 중인 질문");
  const trigger = screen.getByRole("button", {name: "메뉴 열기"});
  expect(screen.getByRole("link", {name: "RAG 대화"})).toHaveAttribute("aria-current", "page");
  await user.click(trigger);
  const drawer = screen.getByRole("dialog", {name: "비공개 작업소 메뉴"});
  expect(within(drawer).getByRole("link", {name: "AI Lab"})).toBeVisible();
  expect(within(drawer).queryByRole("link", {name: "관리자"})).not.toBeInTheDocument();
  await user.click(within(drawer).getByRole("button", {name: "메뉴 닫기"}));
  expect(trigger).toHaveFocus();
  expect(screen.getByRole("textbox", {name: "질문"})).toBe(draft);
  expect(draft).toHaveValue("작성 중인 질문");
});

it("resizes the desktop menu and remembers explicit choices across chat navigation and reloads", async () => {
  const user = userEvent.setup();
  const page = () => <ApplicationShell area="workspace" user={owner}><textarea aria-label="작업 초안" /></ApplicationShell>;
  route.pathname = "/workshop/learning";
  const {rerender, unmount} = render(page());
  try {
    const handle = screen.getByRole("separator", {name: "작업소 메뉴 너비"});
    handle.focus();
    await user.keyboard("{ArrowRight}");
    expect(handle).toHaveAttribute("aria-valuenow", "304");
    await user.keyboard("{Home}{ArrowLeft}");
    expect(handle).toHaveAttribute("aria-valuenow", "256");
    await user.keyboard("{End}{ArrowRight}");
    expect(handle).toHaveAttribute("aria-valuenow", "400");
    const draft = screen.getByRole("textbox", {name: "작업 초안"});
    await user.type(draft, "유지");
    route.pathname = "/workshop/rag/domains/example/chat";
    rerender(page());
    expect(screen.getByRole("button", {name: "메뉴 열기"})).toBeVisible();
    expect(screen.queryByRole("button", {name: /작업소 메뉴 (접기|펼치기)/})).not.toBeInTheDocument();
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
    route.pathname = "/workshop/learning";
    rerender(page());
    expect(screen.getByRole("separator", {name: "작업소 메뉴 너비"})).toHaveAttribute("aria-valuenow", "400");
    await user.click(screen.getByRole("button", {name: "작업소 메뉴 접기"}));
    route.pathname = "/workshop/rag/domains/example/chat";
    rerender(page());
    expect(screen.queryByRole("button", {name: "작업소 메뉴 펼치기"})).not.toBeInTheDocument();
    route.pathname = "/workshop/learning";
    rerender(page());
    await user.click(screen.getByRole("button", {name: "작업소 메뉴 펼치기"}));
    expect(screen.getByRole("separator", {name: "작업소 메뉴 너비"})).toHaveAttribute("aria-valuenow", "400");
    expect(screen.getByRole("textbox", {name: "작업 초안"})).toBe(draft);
    expect(draft).toHaveValue("유지");
    unmount();
    render(page());
    expect(screen.getByRole("separator", {name: "작업소 메뉴 너비"})).toHaveAttribute("aria-valuenow", "400");
  } finally { window.localStorage.clear(); }
});

it("commits a pointer resize on release and discards an interrupted desktop drag", () => {
  route.pathname = "/workshop/learning";
  render(<ApplicationShell area="workspace" user={owner}/>);
  try {
    const handle = screen.getByRole("separator", {name: "작업소 메뉴 너비"});
    const capture = vi.fn();
    Object.defineProperty(handle, "setPointerCapture", {value: capture});
    fireEvent.pointerDown(handle, {pointerId: 1, clientX: 288, button: 0});
    fireEvent.pointerMove(handle, {pointerId: 1, clientX: 304});
    expect(handle).toHaveAttribute("aria-valuenow", "304");
    expect(capture).toHaveBeenCalledWith(1);
    fireEvent.pointerUp(handle, {pointerId: 1, clientX: 300});
    expect(handle).toHaveAttribute("aria-valuenow", "300");
    fireEvent.pointerDown(handle, {pointerId: 2, clientX: 300, button: 0});
    fireEvent.pointerMove(handle, {pointerId: 2, clientX: 380});
    expect(handle).toHaveAttribute("aria-valuenow", "380");
    act(() => { mobile = true; mediaListeners.forEach(listener => listener()); });
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
    act(() => { mobile = false; mediaListeners.forEach(listener => listener()); });
    expect(screen.getByRole("separator")).toHaveAttribute("aria-valuenow", "300");
  } finally { window.localStorage.clear(); }
});

it("shows settings without account data on public pages, closes on Escape or outside interaction", async () => {
  const user = userEvent.setup();
  render(<ApplicationShell area="public" user={owner}><button>본문 동작</button></ApplicationShell>);
  const trigger = screen.getByRole("button", {name:"화면 설정"});
  await user.click(trigger);
  const panel = screen.getByRole("region", {name:"화면 설정"});
  expect(within(panel).getByRole("radio", {name:"라이트"})).toBeVisible();
  expect(within(panel).queryByText(owner.display_name)).not.toBeInTheDocument();
  expect(within(panel).queryByRole("button", {name:"로그아웃"})).not.toBeInTheDocument();
  await user.tab();
  await user.keyboard("{Escape}");
  expect(trigger).toHaveFocus();
  expect(trigger).toHaveAttribute("aria-expanded","false");
  await user.click(trigger);
  await user.click(screen.getByRole("button", {name:"본문 동작"}));
  expect(trigger).toHaveAttribute("aria-expanded","false");
  expect(screen.getByRole("button", {name:"본문 동작"})).toHaveFocus();
});

it("clamps an old saved menu width and keeps one settings control in the chat drawer", async () => {
  const user = userEvent.setup();
  window.localStorage.setItem("ai-workshop.workspace-sidebar.v1", JSON.stringify({width:199, collapsed:false}));
  try {
    route.pathname = "/workshop/learning";
    const {rerender} = render(<ApplicationShell area="workspace" user={owner}/>);
    expect(screen.getByRole("separator", {name:"작업소 메뉴 너비"})).toHaveAttribute("aria-valuenow","256");
    route.pathname = "/workshop/rag/domains/example/chat";
    rerender(<ApplicationShell area="workspace" user={owner}/>);
    expect(screen.getByRole("button", {name:"계정 및 화면 설정"})).toBeVisible();
    await user.click(screen.getByRole("button", {name:"메뉴 열기"}));
    expect(screen.getAllByRole("button", {name:"계정 및 화면 설정"})).toHaveLength(1);
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", {name:"계정 및 화면 설정"}));
    expect(within(dialog).getByRole("radio", {name:"다크"})).toBeVisible();
    await user.keyboard("{Escape}");
    expect(dialog).toBeVisible();
    expect(within(dialog).queryByRole("region", {name:"계정 및 화면 설정"})).not.toBeInTheDocument();
  } finally { window.localStorage.clear(); }
});
