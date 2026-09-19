import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { LibraryPage } from "./api";
import { DocumentBrowser } from "./DocumentBrowser";

const root: LibraryPage = { workspace: { id: "company", name: "회사 자료", kind: "company", expires_at: null }, ancestors: [], folder: null, folders: [], documents: [], next_document_cursor: null, next_folder_cursor: null };
const granted = { read: true, write: true, delete: false, manage_members: false };
function mount() { return render(<DocumentBrowser workspaceId="company" initialLibrary={root} initialRoot={root} initialWorkspaces={[root.workspace]} initialDocument={null} initialVersionId={null} />); }
afterEach(() => vi.unstubAllGlobals());

it("blocks writes during capability loading and after denied rights", async () => {
  let resolve!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>((done) => { resolve = done; })));
  mount();
  expect(screen.getByRole("button", { name: "문서 올리기" })).toBeDisabled();
  await act(async () => resolve(Response.json({ ...granted, write: false })));
  expect(screen.getByRole("button", { name: "새 폴더" })).toBeDisabled();
  expect(screen.getByText(/읽기 전용/)).toBeVisible();
});

it("keeps failed rights inert and retries the capability request explicitly", async () => {
  let reads = 0;
  vi.stubGlobal("fetch", vi.fn(async () => ++reads === 1 ? Response.json({}, { status: 500 }) : Response.json(granted)));
  const user = userEvent.setup(); mount();
  await user.click(await screen.findByRole("button", { name: "권한 다시 확인" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "문서 올리기" })).toBeEnabled());
});

it("locks duplicate folder submissions, preserves the parent and revokes writes after a 403", async () => {
  let resolve!: (value: Response) => void;
  const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => init?.method === "POST" ? new Promise<Response>((done) => { resolve = done; }) : Response.json(granted));
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup(); mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "새 폴더" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "새 폴더" }));
  await user.type(screen.getByLabelText("폴더 이름"), "하위 자료");
  fireEvent.submit(screen.getByRole("form", { name: "새 폴더 만들기" }));
  fireEvent.submit(screen.getByRole("form", { name: "새 폴더 만들기" }));
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
  await act(async () => resolve(Response.json({ error: { code: "forbidden", message: "denied", correlation_id: "test" } }, { status: 403 })));
  expect(screen.getByRole("button", { name: "문서 올리기" })).toBeDisabled();
  expect(screen.getByRole("heading", { name: "root" })).toBeVisible();
});

it("revokes writes after committed upload reconciliation loses authorization without offering another upload", async () => {
  const uploaded = { id: "new", workspace_id: "company", folder_id: null, name: "new.txt", active_version_id: null, latest_version_id: "v1", latest_version: 1, status: "stored", job_id: null };
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => String(input).endsWith("/capabilities") ? Response.json(granted) : init?.method === "POST" ? Response.json(uploaded) : Response.json({ error: { code: "forbidden", message: "denied", correlation_id: "test" } }, { status: 403 }));
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup(); mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "문서 올리기" })).toBeEnabled());
  await user.upload(screen.getByLabelText("새 문서 파일"), new File(["synthetic"], "new.txt", { type: "text/plain" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("문서는 저장됐지만");
  expect(screen.getByRole("button", { name: "문서 올리기" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "업로드 다시 시도" })).not.toBeInTheDocument();
});

it("keeps the mutation lock until folder reconciliation finishes", async () => {
  let resolve!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => String(input).endsWith("/capabilities") ? Response.json(granted) : init?.method === "POST" ? Response.json({ id: "new-folder", parent_id: null, name: "하위" }) : new Promise<Response>((done) => { resolve = done; })));
  const user = userEvent.setup(); mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "새 폴더" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "새 폴더" }));
  await user.type(screen.getByLabelText("폴더 이름"), "하위");
  await user.click(screen.getByRole("button", { name: "폴더 만들기" }));
  expect(screen.getByRole("button", { name: "문서 올리기" })).toBeDisabled();
  await act(async () => resolve(Response.json({ ...root, folders: [{ id: "new-folder", name: "하위", parent_id: null, has_children: false }] })));
  expect(screen.getByRole("heading", { name: "root" })).toBeVisible();
  expect(screen.getByRole("button", { name: "문서 올리기" })).toBeEnabled();
});

it("cancels a folder draft without sending a mutation and returns focus to its opener", async () => {
  const fetcher = vi.fn(async () => Response.json(granted)); vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup(); mount();
  await waitFor(() => expect(screen.getByRole("button", { name: "새 폴더" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "새 폴더" }));
  expect(screen.getByLabelText("폴더 이름")).toHaveFocus();
  await user.type(screen.getByLabelText("폴더 이름"), "미완성");
  await user.click(screen.getByRole("button", { name: "폴더 만들기 취소" }));
  expect(screen.queryByRole("form", { name: "새 폴더 만들기" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "새 폴더" })).toHaveFocus();
  await user.click(screen.getByRole("button", { name: "새 폴더" }));
  expect(screen.getByLabelText("폴더 이름")).toHaveValue("");
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("discards a failed upload file after another action observes revoked authorization", async () => {
  let postCount = 0;
  vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method !== "POST") return Response.json(granted);
    return Response.json({ error: { code: "unavailable", message: "private", correlation_id: "test" } }, { status: ++postCount === 1 ? 500 : 401 });
  }));
  const user = userEvent.setup(); mount();
  await waitFor(() => expect(screen.getByLabelText("새 문서 파일")).toBeEnabled());
  await user.upload(screen.getByLabelText("새 문서 파일"), new File(["synthetic"], "new.txt", { type: "text/plain" }));
  expect(await screen.findByRole("button", { name: "업로드 다시 시도" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: "새 폴더" }));
  await user.type(screen.getByLabelText("폴더 이름"), "하위");
  await user.click(screen.getByRole("button", { name: "폴더 만들기" }));
  await user.click(await screen.findByRole("button", { name: "권한 다시 확인" }));
  await waitFor(() => expect(screen.getByLabelText("새 문서 파일")).toBeEnabled());
  expect(screen.queryByRole("button", { name: "업로드 다시 시도" })).not.toBeInTheDocument();
});

it("starts a new workspace with inert rights and ignores the old pending capability response", async () => {
  let resolve!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => String(input).includes("/company/") ? new Promise<Response>((done) => { resolve = done; }) : Response.json({ ...granted, write: false })));
  const { rerender } = mount();
  const personal = { ...root, workspace: { ...root.workspace, id: "personal", kind: "personal" as const, name: "내 파일" } };
  rerender(<DocumentBrowser workspaceId="personal" initialLibrary={personal} initialRoot={personal} initialWorkspaces={[personal.workspace]} initialDocument={null} initialVersionId={null} />);
  expect(screen.getByRole("button", { name: "문서 올리기" })).toBeDisabled();
  await act(async () => resolve(Response.json(granted)));
  expect(screen.getByRole("button", { name: "문서 올리기" })).toBeDisabled();
  expect(screen.getByRole("heading", { name: "내 파일" })).toBeVisible();
});

it("does not restore writes from a capability response older than an observed authorization denial", async () => {
  let resolve!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => String(input).endsWith("/capabilities") ? new Promise<Response>((done) => { resolve = done; }) : Response.json({ error: { code: "forbidden", message: "private", correlation_id: "test" } }, { status: 403 })));
  const page = { ...root, next_document_cursor: "next" };
  render(<DocumentBrowser workspaceId="company" initialLibrary={page} initialRoot={page} initialWorkspaces={[root.workspace]} initialDocument={null} initialVersionId={null} />);
  await userEvent.click(screen.getByRole("button", { name: "문서 더 보기" }));
  await act(async () => resolve(Response.json(granted)));
  expect(screen.getByRole("button", { name: "문서 올리기" })).toBeDisabled();
});

it.each([
  ["owner", { read: true, write: true, delete: true, manage_members: true }, true],
  ["writer", { read: true, write: true, delete: false, manage_members: false }, true],
  ["reader", { read: true, write: false, delete: false, manage_members: false }, false],
] as const)("uses the returned write capability for a %s without inferring it from membership", async (_role, capabilities, writable) => {
  vi.stubGlobal("fetch", vi.fn(async () => Response.json(capabilities))); mount();
  await waitFor(() => expect(screen.queryByText("파일 관리 권한을 확인하는 중…")).not.toBeInTheDocument());
  const button = screen.getByRole("button", { name: "문서 올리기" });
  if (writable) expect(button).toBeEnabled(); else expect(button).toBeDisabled();
});
