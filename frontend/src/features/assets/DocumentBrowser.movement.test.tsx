import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import type { DocumentSummary, LibraryPage } from "./api";
import { DocumentBrowser } from "./DocumentBrowser";
import { MOVE_MIME } from "./movement";

const workspace = { id: "company", name: "합성 파일함", kind: "company", expires_at: null } as const;
const source: DocumentSummary = { id: "doc", workspace_id: "company", folder_id: "folder-a", metadata_revision: 3, name: "자료.txt", active_version_id: "v1", latest_version_id: "v1", latest_version: 1, status: "ready", job_id: null };
const a = { id: "folder-a", parent_id: null, metadata_revision: 2, name: "A", has_children: false };
const b = { ...a, id: "folder-b", name: "B" };
const root: LibraryPage = { workspace, ancestors: [], folder: null, folders: [a, b], documents: [], next_document_cursor: null, next_folder_cursor: null };
const page: LibraryPage = { ...root, folder: a, folders: [], documents: [source] };
const granted = { read: true, write: true, delete: false, manage_members: false };

function server(options: { post?: () => Promise<Response>; missingRevision?: boolean; denied?: boolean; refreshFail?: boolean } = {}) {
  let committed = false;
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname.endsWith("/capabilities")) return Response.json({ ...granted, write: !options.denied });
    if (init?.method === "POST") { const response = options.post ? await options.post() : Response.json({ ...source, folder_id: b.id, metadata_revision: 4, changed: true }); committed = response.ok; return response; }
    if (committed && options.refreshFail) return Response.json({}, { status: 500 });
    if (url.pathname.endsWith("/documents/doc")) return Response.json({ ...source, folder_id: committed ? b.id : a.id, metadata_revision: options.missingRevision ? undefined : committed ? 4 : 3 });
    const folder = url.searchParams.get("folder_id");
    if (folder === a.id) return Response.json({ ...page, documents: committed ? [] : [source] });
    if (folder === b.id) return Response.json({ ...root, folder: b, folders: [], documents: committed ? [{ ...source, folder_id: b.id, metadata_revision: 4 }] : [] });
    return Response.json(root);
  });
  vi.stubGlobal("fetch", fetcher);
  return () => fetcher.mock.calls.filter(([, init]) => init?.method === "POST");
}
function mount(document = source) { return render(<DocumentBrowser workspaceId="company" initialLibrary={{ ...page, documents: [document] }} initialRoot={root} initialWorkspaces={[workspace]} initialDocument={null} initialVersionId={null} />); }
async function chooseB() {
  const user = userEvent.setup();
  await waitFor(() => expect(screen.getByRole("button", { name: "자료.txt 이동" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "자료.txt 이동" }));
  const dialog = await screen.findByRole("dialog", { name: "이동 확인" });
  await user.click(await within(dialog).findByRole("button", { name: "파일함 최상위" }));
  await user.click(await within(dialog).findByRole("button", { name: "B 목적지 열기" }));
  await waitFor(() => expect(within(dialog).getByRole("button", { name: "여기로 이동" })).toBeEnabled());
  return { user, dialog };
}
afterEach(() => vi.unstubAllGlobals());

it("requires a destination and explicit confirmation then posts the captured revision", async () => {
  const posts = server(); mount(); const { user, dialog } = await chooseB();
  expect(posts()).toHaveLength(0);
  await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(posts()).toHaveLength(1);
  expect(JSON.parse(posts()[0][1]!.body as string)).toEqual({ destination_folder_id: "folder-b", expected_revision: 3 });
  expect(screen.queryByRole("button", { name: "자료.txt 열기" })).not.toBeInTheDocument();
});

it("cancels with Escape and restores opener focus without moving", async () => {
  const posts = server(); mount(); const { user } = await chooseB();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "자료.txt 이동" })).toHaveFocus(); expect(posts()).toHaveLength(0);
});

it("disables a same-parent confirmation", async () => {
  const posts = server(); mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "자료.txt 이동" })).toBeEnabled());
  await userEvent.click(screen.getByRole("button", { name: "자료.txt 이동" }));
  expect(await screen.findByText("이미 이 위치에 있습니다." )).toBeVisible();
  expect(screen.getByRole("button", { name: "여기로 이동" })).toBeDisabled(); expect(posts()).toHaveLength(0);
});

it.each([undefined, 0, -1, 1.5])("does not invent revision %s", async (revision) => {
  server(); mount({ ...source, metadata_revision: revision } as DocumentSummary);
  await waitFor(() => expect(screen.queryByText("파일 관리 권한을 확인하는 중…")).not.toBeInTheDocument());
  expect(screen.getByRole("button", { name: "자료.txt 이동" })).toBeDisabled();
});

it("keeps denied and loading capabilities inert", async () => {
  server({ denied: true }); mount();
  expect(screen.getByRole("button", { name: "자료.txt 이동" })).toBeDisabled();
  await waitFor(() => expect(screen.queryByText("파일 관리 권한을 확인하는 중…")).not.toBeInTheDocument());
  expect(screen.getByRole("button", { name: "자료.txt 이동" })).toBeDisabled();
});

it("locks duplicate confirmation and Escape while the move is in flight", async () => {
  let done!: (response: Response) => void;
  const posts = server({ post: () => new Promise((resolve) => { done = resolve; }) }); mount();
  const { user, dialog } = await chooseB();
  const confirm = within(dialog).getByRole("button", { name: "여기로 이동" });
  fireEvent.click(confirm); fireEvent.click(confirm);
  await waitFor(() => expect(posts()).toHaveLength(1));
  await user.keyboard("{Escape}"); expect(dialog).toBeVisible();
  await act(async () => done(Response.json({ ...source, folder_id: b.id, metadata_revision: 4, changed: true })));
});

it("offers refresh only after commit followed by refresh failure", async () => {
  const posts = server({ refreshFail: true }); mount(); const { user, dialog } = await chooseB();
  await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  expect(await screen.findByText(/이동 완료, 목록 새로고침 필요/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "여기로 이동" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "목록 새로고침" })); expect(posts()).toHaveLength(1);
});

it("retains refresh-only recovery after closing a committed move dialog", async () => {
  const posts = server({ refreshFail: true }); mount(); const { user, dialog } = await chooseB();
  await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  await within(dialog).findByText(/이동 완료, 목록 새로고침 필요/);
  await user.click(within(dialog).getByRole("button", { name: "닫기" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByText(/이동 완료, 목록 새로고침 필요/)).toBeVisible();
  expect(screen.getByRole("button", { name: "자료.txt 이동" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "목록 새로고침" })); expect(posts()).toHaveLength(1);
});

it("ignores OS files and forged drag payloads", async () => {
  const posts = server(); mount();
  const target = screen.getByRole("button", { name: "B 폴더 열기" }).parentElement!;
  const transfer = { types: ["Files", "text/plain"], getData: () => JSON.stringify(source), dropEffect: "copy", files: [new File(["synthetic"], "external.txt")] };
  fireEvent.drop(target, { dataTransfer: transfer });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(posts()).toHaveLength(0);
});

function transfer() {
  const data = new Map<string, string>();
  return { get types() { return [...data.keys()]; }, getData: (type: string) => data.get(type) ?? "", setData: (type: string, value: string) => data.set(type, value), clearData: () => data.clear(), dropEffect: "none", effectAllowed: "all" };
}

it("uses a mounted internal drag token to open the same confirmation without POST", async () => {
  const posts = server(); mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "자료.txt 이동" })).toBeEnabled());
  const sourceRow = screen.getByRole("button", { name: "자료.txt 열기" }).closest("article")!;
  const target = screen.getByRole("button", { name: "B 폴더 열기" }).parentElement!;
  const data = transfer(); fireEvent.dragStart(sourceRow, { dataTransfer: data });
  expect(data.types).toEqual([MOVE_MIME]);
  fireEvent.dragOver(target, { dataTransfer: data }); expect(data.dropEffect).toBe("move"); expect(target).toHaveAttribute("data-drop-state", "allowed");
  fireEvent.drop(target, { dataTransfer: data }); fireEvent.dragEnd(sourceRow, { dataTransfer: data });
  expect(await screen.findByRole("dialog", { name: "이동 확인" })).toBeVisible(); expect(posts()).toHaveLength(0);
  await waitFor(() => expect(screen.getByRole("button", { name: "여기로 이동" })).toBeEnabled());
});

it("rejects mismatched, ended and navigated-away internal sessions", async () => {
  const posts = server(); mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "자료.txt 이동" })).toBeEnabled());
  const sourceRow = screen.getByRole("button", { name: "자료.txt 열기" }).closest("article")!;
  const target = screen.getByRole("button", { name: "B 폴더 열기" }).parentElement!;
  const data = transfer(); fireEvent.dragStart(sourceRow, { dataTransfer: data });
  const forged = transfer(); forged.setData(MOVE_MIME, "forged"); fireEvent.drop(target, { dataTransfer: forged });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.dragStart(sourceRow, { dataTransfer: data }); fireEvent.dragEnd(sourceRow, { dataTransfer: data }); fireEvent.drop(target, { dataTransfer: data });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.dragStart(sourceRow, { dataTransfer: data }); await userEvent.click(screen.getByRole("button", { name: "B 폴더 열기" }));
  fireEvent.drop(screen.getByRole("button", { name: "A 폴더 열기" }).parentElement!, { dataTransfer: data });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(posts()).toHaveLength(0);
});

it("rejects folder self drops and only enables a confirmed different destination", async () => {
  const posts = server(); mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "A 폴더 이동" })).toBeEnabled());
  const row = screen.getByRole("button", { name: "A 폴더 열기" }).parentElement!; const data = transfer();
  fireEvent.dragStart(row, { dataTransfer: data }); fireEvent.dragOver(row, { dataTransfer: data });
  expect(data.dropEffect).toBe("none"); expect(row).toHaveAttribute("data-drop-state", "forbidden");
  fireEvent.drop(row, { dataTransfer: data }); expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "A 폴더 이동" }));
  expect(await screen.findByRole("button", { name: "A 목적지 열기" })).toBeDisabled(); expect(posts()).toHaveLength(0);
});

it("does not silently replace a changed revision before POST", async () => {
  const posts = server({ missingRevision: true }); mount(); const { user, dialog } = await chooseB();
  await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  expect(await within(dialog).findByRole("button", { name: "이동 정보 새로 불러오기" })).toBeVisible(); expect(posts()).toHaveLength(0);
});

it("requires explicit information refresh and confirmation after a 409", async () => {
  let attempts = 0;
  const posts = server({ post: async () => ++attempts === 1 ? Response.json({ error: { code: "asset_revision_conflict", message: "private", correlation_id: "test" } }, { status: 409 }) : Response.json({ ...source, folder_id: b.id, metadata_revision: 4, changed: true }) });
  mount(); const { user, dialog } = await chooseB();
  await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(/변경되었습니다/); expect(posts()).toHaveLength(1);
  await user.click(within(dialog).getByRole("button", { name: "이동 정보 새로 불러오기" }));
  await waitFor(() => expect(within(dialog).getByRole("button", { name: "여기로 이동" })).toBeEnabled()); expect(posts()).toHaveLength(1);
  await user.click(within(dialog).getByRole("button", { name: "여기로 이동" })); await waitFor(() => expect(posts()).toHaveLength(2));
});

it.each([401, 403, 404])("revokes movement commands on %s without retrying POST", async (status) => {
  const posts = server({ post: async () => Response.json({ error: { code: "not_found", message: "private", correlation_id: "test" } }, { status }) });
  mount(); const { user, dialog } = await chooseB(); await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "문서 올리기" })).toBeDisabled());
  expect(posts()).toHaveLength(1);
});

it("does not replay an unknown network outcome", async () => {
  const posts = server({ post: async () => { throw new TypeError("network failed"); } });
  mount(); const { user, dialog } = await chooseB(); await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  expect(await within(dialog).findByRole("button", { name: "목록 새로고침" })).toBeVisible();
  expect(within(dialog).queryByRole("button", { name: "여기로 이동" })).not.toBeInTheDocument();
  await user.click(within(dialog).getByRole("button", { name: "목록 새로고침" })); expect(posts()).toHaveLength(1);
});

it("discards an in-flight preflight when navigating or unmounting", async () => {
  let resolve!: (value: Response) => void;
  const posts = server();
  const fetcher = globalThis.fetch;
  vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => String(input).endsWith("/documents/doc") ? new Promise<Response>((done) => { resolve = done; }) : fetcher(input, init)));
  const view = mount(); const { user, dialog } = await chooseB(); await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  view.unmount(); await act(async () => resolve(Response.json(source))); expect(posts()).toHaveLength(0);
});

it("moves a folder with its captured revision and keeps the current folder ID with fresh ancestry", async () => {
  let committed = false; const reads: (string | null)[] = [];
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname.endsWith("/capabilities")) return Response.json(granted);
    if (init?.method === "POST") { committed = true; return Response.json({ id: a.id, name: a.name, workspace_id: workspace.id, parent_id: b.id, metadata_revision: 3, changed: true }); }
    const folderId = url.searchParams.get("folder_id"); reads.push(folderId);
    if (folderId === a.id) return Response.json({ ...page, folder: committed ? { ...a, parent_id: b.id, metadata_revision: 3 } : a, ancestors: committed ? [b] : [] });
    if (folderId === b.id) return Response.json({ ...root, folder: b, folders: committed ? [{ ...a, parent_id: b.id, metadata_revision: 3 }] : [] });
    return Response.json({ ...root, folders: committed ? [{ ...b, has_children: true }] : [a, b] });
  });
  vi.stubGlobal("fetch", fetcher); mount(); const user = userEvent.setup();
  await waitFor(() => expect(screen.getByRole("button", { name: "A 폴더 이동" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "A 폴더 이동" }));
  const dialog = screen.getByRole("dialog", { name: "이동 확인" });
  await user.click(await within(dialog).findByRole("button", { name: "B 목적지 열기" }));
  await waitFor(() => expect(within(dialog).getByRole("button", { name: "여기로 이동" })).toBeEnabled());
  await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  const post = fetcher.mock.calls.find(([, init]) => init?.method === "POST")!;
  expect(post[0]).toBe("/api/v1/workspaces/company/folders/folder-a/move");
  expect(JSON.parse(post[1]!.body as string)).toEqual({ destination_folder_id: "folder-b", expected_revision: 2 });
  expect(screen.getByRole("heading", { name: "A" })).toBeVisible();
  expect(screen.getByRole("navigation", { name: "현재 폴더 경로" })).toHaveTextContent("B");
  expect(reads).toEqual(expect.arrayContaining([null, "folder-a", "folder-b"]));
});

it("drills into paginated destination folders without duplicate rows", async () => {
  const posts = server(); const fetcher = globalThis.fetch;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname.endsWith("/library") && !url.searchParams.has("folder_id")) return Response.json(url.searchParams.has("folder_cursor") ? { ...root, folders: [a, b] } : { ...root, folders: [a], next_folder_cursor: "next-folders" });
    return fetcher(input, init);
  }));
  mount(); const user = userEvent.setup();
  await waitFor(() => expect(screen.getByRole("button", { name: "자료.txt 이동" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "자료.txt 이동" })); const dialog = screen.getByRole("dialog", { name: "이동 확인" });
  await waitFor(() => expect(within(dialog).getByRole("button", { name: "파일함 최상위" })).toBeEnabled());
  await user.click(within(dialog).getByRole("button", { name: "파일함 최상위" }));
  await user.click(await within(dialog).findByRole("button", { name: "목적지 폴더 더 보기" }));
  expect(await within(dialog).findByRole("button", { name: "B 목적지 열기" })).toBeVisible();
  expect(within(dialog).getAllByRole("button", { name: "A 목적지 열기" })).toHaveLength(1); expect(posts()).toHaveLength(0);
});

it("does not publish a late successful move into a newer workspace", async () => {
  let resolve!: (response: Response) => void;
  const posts = server({ post: () => new Promise((done) => { resolve = done; }) });
  const view = mount(); const { user, dialog } = await chooseB();
  await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  const personal = { ...root, workspace: { ...workspace, id: "personal", name: "새 공간", kind: "personal" as const }, folders: [] };
  view.rerender(<DocumentBrowser workspaceId="personal" initialLibrary={personal} initialRoot={personal} initialWorkspaces={[personal.workspace]} initialDocument={null} initialVersionId={null} />);
  await act(async () => resolve(Response.json({ ...source, folder_id: b.id, metadata_revision: 4, changed: true })));
  expect(screen.getByRole("heading", { name: "새 공간" })).toBeVisible();
  expect(screen.queryByText("이동을 완료했습니다.")).not.toBeInTheDocument(); expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("publishes the moved open document's canonical location and restores its viewer from that URL", async () => {
  const posts = server(); const fetcher = globalThis.fetch;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/versions")) return Response.json({ items: [{ id: "v1", number: 1, media_type: "text/plain", size: 9, status: "ready" }], next_cursor: null });
    if (path.endsWith("/preview")) return Response.json({ asset_version_id: "v1", document_id: "doc", kind: "text", name: source.name, page_count: null, size: 9, text: "synthetic", version: 1 });
    return fetcher(input, init);
  }));
  mount(); const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "자료.txt 열기" }));
  await screen.findByText("synthetic");
  const { dialog } = await chooseB(); await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  expect(screen.getByRole("complementary")).toBeVisible();
  expect(new URLSearchParams(window.location.search).get("folder")).toBe("folder-b");
  expect(new URLSearchParams(window.location.search).get("document")).toBe("doc");
  expect(new URLSearchParams(window.location.search).get("version")).toBe("v1");
  await act(async () => window.dispatchEvent(new PopStateEvent("popstate")));
  await waitFor(() => expect(screen.getByRole("heading", { name: "B" })).toBeVisible());
  expect(await screen.findByText("synthetic")).toBeVisible(); expect(posts()).toHaveLength(1);
}, 15_000);

it("contains forward and reverse Tab while every move button is disabled during POST", async () => {
  let resolve!: (response: Response) => void;
  const posts = server({ post: () => new Promise((done) => { resolve = done; }) });
  mount(); const { user, dialog } = await chooseB();
  await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  await waitFor(() => expect(posts()).toHaveLength(1));
  expect(within(dialog).getAllByRole("button").every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
  await user.tab(); expect(dialog.contains(document.activeElement)).toBe(true);
  await user.tab({ shift: true }); expect(dialog.contains(document.activeElement)).toBe(true);
  await user.keyboard("{Escape}"); expect(dialog).toBeVisible();
  await act(async () => resolve(Response.json({ ...source, folder_id: b.id, metadata_revision: 4, changed: true })));
}, 15_000);

it("closes the move dialog before the open viewer when Escape is pressed", async () => {
  const posts = server(); const fetcher = globalThis.fetch;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).endsWith("/versions")) return Response.json({ items: [], next_cursor: null });
    if (String(input).endsWith("/preview")) return Response.json({ asset_version_id: "v1", document_id: "doc", kind: "text", name: source.name, page_count: null, size: 9, text: "synthetic", version: 1 });
    return fetcher(input, init);
  }));
  mount(); await userEvent.click(screen.getByRole("button", { name: "자료.txt 열기" }));
  await screen.findByText("synthetic"); const { user } = await chooseB();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("complementary")).toBeVisible(); expect(posts()).toHaveLength(0);
}, 15_000);

it.each(["close", "open", "version"] as const)("does not republish an old viewer after %s during delayed refresh-only recovery", async (interaction) => {
  const other = { ...source, id: "other-doc", name: "다른 문서.txt", metadata_revision: 1 };
  let committed = false; let allowRefresh = false; let delayRead = true; let finishRead!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname.endsWith("/capabilities")) return Response.json(granted);
    if (url.pathname.endsWith("/versions")) return Response.json({ items: [{ id: "v1", number: 1, media_type: "text/plain", size: 9, status: "ready" }, { id: "v2", number: 2, media_type: "text/plain", size: 9, status: "ready" }], next_cursor: null });
    if (url.pathname.endsWith("/preview")) return Response.json({ asset_version_id: url.pathname.includes("v2") ? "v2" : "v1", document_id: url.pathname.includes("other-doc") ? "other-doc" : "doc", kind: "text", name: source.name, page_count: null, size: 9, text: "synthetic", version: url.pathname.includes("v2") ? 2 : 1 });
    if (init?.method === "POST") { committed = true; return Response.json({ ...source, folder_id: b.id, metadata_revision: 4, changed: true }); }
    if (committed && !allowRefresh) return Response.json({}, { status: 500 });
    if (url.pathname.endsWith("/documents/doc")) return committed
      ? delayRead ? new Promise<Response>((resolve) => { finishRead = resolve; }) : Response.json({ ...source, folder_id: b.id, metadata_revision: 4 })
      : Response.json(source);
    const folderId = url.searchParams.get("folder_id");
    return Response.json(folderId === a.id ? { ...page, documents: committed ? [other] : [source, other] } : folderId === b.id ? { ...root, folder: b, folders: [], documents: [] } : root);
  }));
  render(<DocumentBrowser workspaceId="company" initialLibrary={{ ...page, documents: [source, other] }} initialRoot={root} initialWorkspaces={[workspace]} initialDocument={null} initialVersionId={null} />);
  const user = userEvent.setup(); await user.click(screen.getByRole("button", { name: "자료.txt 열기" })); await screen.findByText("synthetic");
  const { dialog } = await chooseB(); await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  await within(dialog).findByText(/이동 완료, 목록 새로고침 필요/);
  await user.click(within(dialog).getByRole("button", { name: "닫기" }));
  allowRefresh = true;
  await user.click(screen.getByRole("button", { name: "목록 새로고침" }));
  await waitFor(() => expect(finishRead).toBeTypeOf("function"));
  if (interaction === "close") await user.click(screen.getByRole("button", { name: "문서 닫기" }));
  if (interaction === "open") {
    const otherOpener = screen.getByRole("button", { name: "다른 문서.txt 열기" });
    expect(otherOpener).toBeDisabled();
    await user.click(otherOpener);
  }
  if (interaction === "version") await user.click(screen.getByRole("button", { name: /버전 2/ }));
  const currentUrl = window.location.href;
  delayRead = false;
  await act(async () => finishRead(Response.json({ ...source, folder_id: b.id, metadata_revision: 4 })));
  if (interaction === "close") expect(window.location.href).toBe(currentUrl);
  if (interaction === "close") expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  if (interaction === "open") {
    expect(within(screen.getByRole("complementary")).getByRole("heading", { name: "자료.txt 원문" })).toBeVisible();
    expect(new URLSearchParams(window.location.search).get("folder")).toBe(b.id);
    expect(new URLSearchParams(window.location.search).get("document")).toBe(source.id);
  }
  expect(screen.getByRole("button", { name: "다른 문서.txt 열기" })).toBeEnabled();
  if (interaction === "version") {
    const restoredSelection = new URLSearchParams(window.location.search);
    expect(restoredSelection.get("folder")).toBe(b.id);
    expect(restoredSelection.get("document")).toBe(source.id);
    expect(restoredSelection.get("version")).toBe("v2");
    await act(async () => window.dispatchEvent(new PopStateEvent("popstate")));
    await screen.findByRole("heading", { name: "B" });
    expect(await screen.findByText("synthetic")).toBeVisible();
    expect(screen.getByRole("button", { name: /버전 2/ })).toHaveAttribute("aria-pressed", "true");
  }
}, 15_000);

it("blocks opening a stale row while recovery that began without a viewer is delayed", async () => {
  const posts = server({ refreshFail: true }); const fetcher = globalThis.fetch;
  let recovering = false; let reads = 0; let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    if (recovering && url.pathname.endsWith("/library")) {
      reads += 1; await gate;
      const folderId = url.searchParams.get("folder_id");
      return Response.json(folderId === a.id ? { ...page, documents: [] } : folderId === b.id ? { ...root, folder: b, folders: [], documents: [{ ...source, folder_id: b.id, metadata_revision: 4 }] } : root);
    }
    return fetcher(input, init);
  }));
  mount(); const { user, dialog } = await chooseB();
  await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  await within(dialog).findByText(/이동 완료, 목록 새로고침 필요/);
  await user.click(within(dialog).getByRole("button", { name: "닫기" }));
  recovering = true;
  await user.click(screen.getByRole("button", { name: "목록 새로고침" }));
  await waitFor(() => expect(reads).toBeGreaterThan(0));
  const opener = screen.getByRole("button", { name: "자료.txt 열기" });
  expect(opener).toBeDisabled();
  const currentUrl = window.location.href;
  await user.click(opener);
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  await act(async () => release());
  await waitFor(() => expect(screen.queryByRole("button", { name: "자료.txt 열기" })).not.toBeInTheDocument());
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  expect(window.location.href).toBe(currentUrl); expect(posts()).toHaveLength(1);
}, 15_000);
