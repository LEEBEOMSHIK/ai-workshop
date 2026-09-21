import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { ConversationAttachments } from "./ConversationAttachments";

const json = (value: unknown) => new Response(JSON.stringify(value), {headers: {"content-type": "application/json"}});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

it("disables PC upload when no eligible private workspace exists", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => json(String(url).endsWith("attachment-options") ? {workspaces: [], reason_code: "no_private_attachment_workspace"} : [])));
  render(<ConversationAttachments slug="example" sessionId="session" ensureSession={vi.fn()} onBusy={vi.fn()} onSelect={vi.fn()} />);
  expect(await screen.findByText(/첨부할 수 있는 개인 공간이 없습니다/)).toBeVisible();
  expect(screen.getByLabelText("PC 파일 선택")).toBeDisabled();
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
