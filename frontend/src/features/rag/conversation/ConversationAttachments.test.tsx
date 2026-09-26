import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { ConversationAttachments } from "./ConversationAttachments";

const json = (value: unknown) => new Response(JSON.stringify(value), {headers: {"content-type": "application/json"}});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

it("finishes a stored upload without selecting it and excludes only its visible card", async () => {
  const selected = vi.fn();
  const busy = vi.fn();
  const document = {id: "private-document", name: "private.txt", workspace_id: "private", status: "ready"};
  const fetcher = vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("attachment-options")) return json({workspaces: [{id: "private", name: "개인"}]});
    if (init?.method === "POST") return json({id: "attachment", document, status: "stored", error_code: "attachment_outside_generation_scope"});
    return json([]);
  });
  vi.stubGlobal("fetch", fetcher);
  render(<ConversationAttachments slug="example" sessionId="session" ensureSession={vi.fn()} onBusy={busy} onSelect={selected} pendingFiles={[new File(["synthetic"], "private.txt")]} />);
  expect(await screen.findByText("private.txt · 저장됨 · 현재 답변에 사용 불가")).toBeVisible();
  expect(screen.getByText("현재 대화의 검색·생성 범위에 포함되지 않은 개인 파일입니다.")).toBeVisible();
  expect(screen.queryByText("attachment_outside_generation_scope")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "질문에 추가"})).not.toBeInTheDocument();
  expect(selected).not.toHaveBeenCalled();
  expect(busy).toHaveBeenLastCalledWith(false);
  fireEvent.click(screen.getByRole("button", {name: "제외"}));
  expect(screen.queryByText(/저장됨 · 현재 답변에 사용 불가/)).not.toBeInTheDocument();
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "DELETE")).toBe(false);
});

it("ends processing when polling reports storage outside generation scope", async () => {
  vi.useFakeTimers();
  const selected = vi.fn();
  const busy = vi.fn();
  let status: "stored" | "ready" | null = null;
  const document = {id: "private-document", name: "private.txt", workspace_id: "private", status: "ready"};
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("attachment-options")) return json({workspaces: [{id: "private", name: "개인"}]});
    if (init?.method === "POST") return json({id: "attachment", document: null, status: "processing"});
    return json(status ? [{id: "attachment", document, status, error_code: status === "stored" ? "attachment_outside_generation_scope" : null}] : []);
  }));
  await act(async () => { render(<ConversationAttachments slug="example" sessionId="session" ensureSession={vi.fn()} onBusy={busy} onSelect={selected} pendingFiles={[new File(["synthetic"], "private.txt")]} />); });
  expect(busy).toHaveBeenLastCalledWith(true);
  status = "stored";
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(screen.getByText("private.txt · 저장됨 · 현재 답변에 사용 불가")).toBeVisible();
  expect(selected).not.toHaveBeenCalled();
  expect(busy).toHaveBeenLastCalledWith(false);
  status = "ready";
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(screen.getByRole("button", {name: "질문에 추가"})).toBeVisible();
  expect(selected).not.toHaveBeenCalled();
});

it("retains dropped files while options load and uploads them sequentially", async () => {
  let resolveOptions!: (response: Response) => void;
  let resolveFirst!: (response: Response) => void;
  const posts: string[] = [];
  const consumed = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("attachment-options")) return new Promise<Response>(resolve => { resolveOptions = resolve; });
    if (init?.method === "POST") {
      posts.push(((init.body as FormData).get("file") as File).name);
      if (posts.length === 1) return new Promise<Response>(resolve => { resolveFirst = resolve; });
      return json({id: "second", status: "processing", document: null});
    }
    return json([]);
  }));
  const files = [new File(["synthetic"], "first.txt"), new File(["synthetic"], "second.txt")];
  render(<ConversationAttachments slug="example" sessionId="session" ensureSession={vi.fn()} onBusy={vi.fn()} onSelect={vi.fn()} pendingFiles={files} onFilesConsumed={consumed} />);
  expect(await screen.findByText("first.txt")).toBeVisible();
  expect(posts).toEqual([]);
  await act(async () => { resolveOptions(json({workspaces: [{id: "private", name: "개인", kind: "personal"}]})); });
  expect(posts).toEqual(["first.txt"]);
  await act(async () => { resolveFirst(json({id: "first", status: "processing", document: null})); });
  await waitFor(() => expect(posts).toEqual(["first.txt", "second.txt"]));
  expect(consumed).toHaveBeenCalledTimes(1);
});

it("disables PC upload when no eligible private workspace exists", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => json(String(url).endsWith("attachment-options") ? {workspaces: [], reason_code: "no_private_attachment_workspace"} : [])));
  render(<ConversationAttachments slug="example" sessionId="session" ensureSession={vi.fn()} onBusy={vi.fn()} onSelect={vi.fn()} />);
  expect(await screen.findByText(/첨부할 수 있는 개인 공간이 없습니다/)).toBeVisible();
  expect(screen.getByLabelText("PC 파일 선택")).toBeDisabled();
});

it("keeps a dropped file removable without uploading to an ineligible workspace", async () => {
  const busy = vi.fn();
  const fetcher = vi.fn(async (url: RequestInfo | URL) => json(String(url).endsWith("attachment-options") ? {workspaces: []} : []));
  vi.stubGlobal("fetch", fetcher);
  render(<ConversationAttachments slug="example" sessionId="session" ensureSession={vi.fn()} onBusy={busy} onSelect={vi.fn()} pendingFiles={[new File(["synthetic"], "waiting.txt")]} />);
  expect(await screen.findByText(/첨부할 수 있는 개인 공간이 없습니다/)).toBeVisible();
  expect(screen.getByText("waiting.txt")).toBeVisible();
  fireEvent.click(screen.getByRole("button", {name: "waiting.txt 첨부 취소"}));
  expect(busy).toHaveBeenLastCalledWith(false);
  expect(fetcher.mock.calls.every(([url]) => !String(url).includes("workspace_id="))).toBe(true);
});

it("waits for an explicit destination when multiple private workspaces are eligible", async () => {
  const posts: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("attachment-options")) return json({workspaces: [{id: "one", name: "개인 1"}, {id: "two", name: "개인 2"}]});
    if (init?.method === "POST") { posts.push(String(url)); return json({id: "attached", status: "processing", document: null}); }
    return json([]);
  }));
  render(<ConversationAttachments slug="example" sessionId="session" ensureSession={vi.fn()} onBusy={vi.fn()} onSelect={vi.fn()} pendingFiles={[new File(["synthetic"], "waiting.txt")]} />);
  const workspace = await screen.findByLabelText("첨부 저장 위치");
  expect(posts).toEqual([]);
  fireEvent.change(workspace, {target: {value: "two"}});
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).toContain("workspace_id=two");
});

it("keeps sending blocked when polling returns no row during the upload POST", async () => {
  vi.useFakeTimers();
  let resolveUpload!: (response: Response) => void;
  const busy = vi.fn();
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("attachment-options")) return json({workspaces: [{id: "private", name: "개인", kind: "personal"}]});
    if (init?.method === "POST") return new Promise<Response>(resolve => {resolveUpload = resolve;});
    return json([]);
  }));
  await act(async () => { render(<ConversationAttachments slug="example" sessionId="session" ensureSession={vi.fn()} onBusy={busy} onSelect={vi.fn()} />); });
  await act(async () => { fireEvent.change(screen.getByLabelText("PC 파일 선택"), {target: {files: [new File(["synthetic"], "sample.txt")]}}); });
  expect(busy).toHaveBeenLastCalledWith(true);
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(busy).toHaveBeenLastCalledWith(true);
  await act(async () => {resolveUpload(json({id: "attachment", document: null, status: "processing"}));});
  expect(busy).toHaveBeenLastCalledWith(true);
});

it("adds all files becoming ready in one poll as a single selection update", async () => {
  vi.useFakeTimers();
  const selected = vi.fn();
  const documents = ["first", "second"].map(id => ({id, name: `${id}.txt`, workspace_id: "private", status: "ready"}));
  let uploads = 0;
  let ready = false;
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    if (String(url).endsWith("attachment-options")) return json({workspaces: [{id: "private", name: "개인", kind: "personal"}]});
    if (init?.method === "POST") { const document = documents[uploads++]; return json({id: document.id, document, status: "processing"}); }
    return json(ready ? documents.map(document => ({id: document.id, document, status: "ready"})) : []);
  }));
  await act(async () => { render(<ConversationAttachments slug="example" sessionId="session" ensureSession={vi.fn()} onBusy={vi.fn()} onSelect={selected} />); });
  for (const document of documents) await act(async () => { fireEvent.change(screen.getByLabelText("PC 파일 선택"), {target: {files: [new File(["synthetic"], document.name)]}}); });
  ready = true;
  await act(async () => { await vi.advanceTimersByTimeAsync(5000); });
  expect(selected).toHaveBeenCalledTimes(1);
  expect(selected).toHaveBeenCalledWith(documents);
});

it("uploads privately and permits ready documents to be selected without granting external approval", async () => {
  const selected = vi.fn();
  const busy = vi.fn();
  const uploaded: Array<{path: string; init: RequestInit}> = [];
  const document = {id: "document", name: "sample.txt", workspace_id: "private", status: "ready"};
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (path.endsWith("attachment-options")) return json({workspaces: [{id: "private", name: "개인 자료", kind: "personal"}], reason_code: null});
    if (init?.method === "POST") { uploaded.push({path, init}); return json({id: "attachment", document, status: "ready", error_code: null}); }
    return json([]);
  }));
  render(<ConversationAttachments slug="example" sessionId="session" ensureSession={vi.fn()} onBusy={busy} onSelect={selected} />);
  await waitFor(() => expect(screen.getByLabelText("PC 파일 선택")).toBeEnabled());
  const file = new File(["synthetic"], "sample.txt", {type: "text/plain"});
  fireEvent.change(screen.getByLabelText("PC 파일 선택"), {target: {files: [file]}});
  await waitFor(() => expect(selected).toHaveBeenCalledWith([document]));
  expect(uploaded[0].path).toContain("/conversations/session/attachments?workspace_id=private");
  expect((uploaded[0].init.body as FormData).get("file")).toBe(file);
  expect((uploaded[0].init.body as FormData).has("classification")).toBe(false);
  expect(busy).toHaveBeenLastCalledWith(false);
});
