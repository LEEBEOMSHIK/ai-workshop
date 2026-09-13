import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import { DomainFileCabinet } from "./DomainFileCabinet";
import type { LibraryPage } from "../../assets/api";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
const workspace = { id: "company", name: "합성 공간", kind: "company", expires_at: null } as const;
const a = { id: "a", name: "A", parent_id: null, metadata_revision: 1, has_children: false };
const b = { ...a, id: "b", name: "B" };
const doc = { id: "doc", name: "자료.txt", workspace_id: "company", folder_id: "a", metadata_revision: 3, active_version_id: "v1", latest_version_id: "v1", latest_version: 1, status: "ready", job_id: null } as const;
const root: LibraryPage = { workspace, folder: null, ancestors: [], folders: [a, b], documents: [], next_document_cursor: null, next_folder_cursor: null };
const page: LibraryPage = { ...root, folder: a, folders: [], documents: [doc] };
const context = { domain_id: "domain", display_name: "합성 도메인", connection_version_id: "connection", selection_limit: 5, workspace_options: [workspace] };
afterEach(() => vi.unstubAllGlobals());

function setup(options: { bounded?: boolean; changedVersion?: boolean; delayRevalidation?: boolean; lostResponse?: boolean; emptySelection?: boolean; refreshFail?: boolean } = {}) {
  let committed = false; let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname.endsWith("/capabilities")) return Response.json({ read: true, write: true, delete: false, manage_members: false });
    if (init?.method === "POST") { committed = true; if (options.lostResponse) throw new TypeError("lost response"); return Response.json({ id: doc.id, name: doc.name, workspace_id: workspace.id, folder_id: "b", metadata_revision: 4, changed: true }); }
    if (committed && options.refreshFail) return Response.json({}, { status: 500 });
    if (!url.pathname.includes("/rag/domains/demo/library/workspaces/company")) throw new Error(`Unexpected Platform read ${url.pathname}`);
    if (url.pathname.endsWith("/documents/doc")) {
      if (committed && options.delayRevalidation) await gate;
      return Response.json({ ...doc, folder_id: committed ? "b" : "a", metadata_revision: committed ? 4 : 3, active_version_id: committed && options.changedVersion ? "v2" : "v1" });
    }
    const folderId = url.searchParams.get("folder_id");
    return Response.json(folderId === "a" ? { ...page, documents: committed ? [] : [doc] } : folderId === "b" ? { ...root, folder: b, folders: [], documents: [] } : root);
  });
  vi.stubGlobal("fetch", fetcher);
  const apply = vi.fn(); const invalidated = vi.fn();
  render(<DomainFileCabinet embedded slug="demo" context={context} initialLibrary={page} initialRoot={root} initialDocument={null} initialVersionId={null} initialSelectedDocuments={options.emptySelection ? [] : [doc]} onApplySelection={apply} onSelectionInvalidated={invalidated} allowedFolderIdsByWorkspace={options.bounded ? { company: ["a"] } : undefined} />);
  return { apply, invalidated, fetcher, release };
}
async function move() {
  const user = userEvent.setup();
  await waitFor(() => expect(screen.getByRole("button", { name: "자료.txt 이동" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "자료.txt 이동" }));
  const dialog = screen.getByRole("dialog", { name: "이동 확인" });
  await waitFor(() => expect(within(dialog).getByRole("button", { name: "파일함 최상위" })).toBeEnabled());
  await user.click(within(dialog).getByRole("button", { name: "파일함 최상위" }));
  await user.click(await within(dialog).findByRole("button", { name: "B 목적지 열기" }));
  await waitFor(() => expect(within(dialog).getByRole("button", { name: "여기로 이동" })).toBeEnabled());
  await user.click(within(dialog).getByRole("button", { name: "여기로 이동" }));
  return user;
}
it("preserves ID selection and refreshes metadata for unrestricted position-only movement", async () => {
  const { apply, invalidated } = setup(); const user = await move();
  await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  await user.click(screen.getByRole("button", { name: "선택 문서로 대화" }));
  expect(apply).toHaveBeenCalledWith([expect.objectContaining({ id: "doc", folder_id: "b", metadata_revision: 4, active_version_id: "v1" })]);
  expect(invalidated).not.toHaveBeenCalled();
});
it("allows authorized moves beyond fixed search folders and invalidates the parent without widening", async () => {
  const { apply, invalidated, fetcher } = setup({ bounded: true }); await move();
  await waitFor(() => expect(invalidated).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
  expect(screen.getByText(/다시 선택해 주세요/)).toBeVisible();
  expect(apply).not.toHaveBeenCalled();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});
it("invalidates the entire selection when active version changed", async () => {
  const { invalidated } = setup({ changedVersion: true }); await move();
  await waitFor(() => expect(invalidated).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
});
it("blocks Apply while selected documents are being revalidated", async () => {
  const { release } = setup({ delayRevalidation: true }); await move();
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
  await act(async () => release());
  await waitFor(() => expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeEnabled());
});

it("invalidates parent selection when a POST response is lost instead of assuming no move", async () => {
  const { invalidated } = setup({ bounded: true, lostResponse: true }); await move();
  await waitFor(() => expect(invalidated).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "여기로 이동" })).not.toBeInTheDocument();
});

it("blocks selecting a stale moved row after failed recovery with initially empty bounded selection", async () => {
  const { apply } = setup({ bounded: true, emptySelection: true, refreshFail: true });
  const user = await move(); const dialog = screen.getByRole("dialog");
  await within(dialog).findByText(/이동 완료, 목록 새로고침 필요/);
  await user.click(within(dialog).getByRole("button", { name: "닫기" }));
  const checkbox = screen.getByRole("checkbox", { name: "자료.txt 선택" });
  expect(checkbox).toBeDisabled();
  await user.click(checkbox);
  expect(checkbox).not.toBeChecked();
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
  expect(apply).not.toHaveBeenCalled();
}, 15_000);

function switchingCabinet(options: { pendingValidation?: boolean; pendingPost?: boolean; selectedInOtherWorkspace?: boolean; knownRejection?: boolean }) {
  const other = { ...workspace, id: "other", name: "다른 공간" };
  const oldOther = { ...doc, id: "old-other", workspace_id: "other", folder_id: null, name: "이전 선택.txt" };
  const newOther = { ...oldOther, id: "new-other", name: "새 선택.txt" };
  let committed = false; let finishValidation!: () => void; let rejectPost!: (error: Error) => void;
  const validation = new Promise<void>((resolve) => { finishValidation = resolve; });
  const post = new Promise<Response>((_resolve, reject) => { rejectPost = reject; });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(String(input), "http://localhost");
    if (url.pathname.endsWith("/capabilities")) return Response.json({ read: true, write: true, delete: false, manage_members: false });
    if (init?.method === "POST") {
      if (options.pendingPost) return post;
      if (options.knownRejection) return Response.json({ error: { code: "folder_exists", message: "conflict", correlation_id: "synthetic" } }, { status: 409 });
      committed = true; return Response.json({ ...doc, folder_id: "b", metadata_revision: 4, changed: true });
    }
    if (url.pathname.includes("/workspaces/other")) return Response.json({ ...root, workspace: other, folders: [], documents: [oldOther, newOther] });
    if (url.pathname.endsWith("/documents/doc")) {
      if (committed && options.pendingValidation) await validation;
      return Response.json({ ...doc, folder_id: committed ? "b" : "a", metadata_revision: committed ? 4 : 3 });
    }
    const id = url.searchParams.get("folder_id");
    return Response.json(id === "a" ? { ...page, documents: committed ? [] : [doc] } : id === "b" ? { ...root, folder: b, folders: [] } : root);
  }));
  const invalidated = vi.fn(); const apply = vi.fn();
  window.history.replaceState(null, "", "/workshop/rag/domains/demo/files?workspace=company&folder=a");
  render(<DomainFileCabinet slug="demo" context={{ ...context, workspace_options: [workspace, other] }} initialLibrary={page} initialRoot={root} initialDocument={null} initialVersionId={null} initialSelectedDocuments={options.selectedInOtherWorkspace ? [oldOther] : [doc]} onApplySelection={apply} onSelectionInvalidated={invalidated} />);
  return { invalidated, apply, finishValidation, rejectPost, newOther };
}

async function restoreOtherWorkspace() {
  await act(async () => {
    window.history.replaceState(null, "", "/workshop/rag/domains/demo/files?workspace=other");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await screen.findByRole("heading", { name: "다른 공간" });
}

it("keeps a committed selection validation obligation when history switches workspace", async () => {
  const { invalidated, apply, finishValidation } = switchingCabinet({ pendingValidation: true });
  await move(); await screen.findByText("선택 문서의 현재 위치와 활성 버전을 확인하는 중…");
  await restoreOtherWorkspace();
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
  expect(invalidated).toHaveBeenCalledTimes(1); expect(apply).not.toHaveBeenCalled();
  await act(async () => finishValidation());
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
}, 15_000);

it("ignores a late rejected POST after workspace navigation and explicit replacement selection", async () => {
  const { invalidated, apply, rejectPost, newOther } = switchingCabinet({ pendingPost: true, selectedInOtherWorkspace: true });
  const user = await move();
  await restoreOtherWorkspace();
  await user.click(screen.getByRole("checkbox", { name: "이전 선택.txt 선택" }));
  await user.click(screen.getByRole("checkbox", { name: "새 선택.txt 선택" }));
  await act(async () => rejectPost(new TypeError("late network rejection")));
  expect(invalidated).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "선택 문서로 대화" }));
  expect(apply).toHaveBeenCalledWith([newOther]);
}, 15_000);

it("retains the initiating selection's uncertainty before aborting a pending POST on navigation", async () => {
  const { invalidated, rejectPost } = switchingCabinet({ pendingPost: true });
  await move(); await restoreOtherWorkspace();
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
  expect(invalidated).toHaveBeenCalledTimes(1);
  await act(async () => rejectPost(new DOMException("aborted", "AbortError")));
  expect(invalidated).toHaveBeenCalledTimes(1);
}, 15_000);

it("releases the initiating selection obligation after a known rejected move", async () => {
  const { invalidated } = switchingCabinet({ knownRejection: true }); const user = await move();
  await screen.findByRole("button", { name: "이동 정보 새로 불러오기" });
  await user.click(screen.getByRole("button", { name: "이동 취소" }));
  await restoreOtherWorkspace();
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeEnabled(); expect(invalidated).not.toHaveBeenCalled();
}, 15_000);

it("retires the initiating selection before same-workspace history navigation aborts a pending POST", async () => {
  const { invalidated, rejectPost } = switchingCabinet({ pendingPost: true });
  await move();
  await act(async () => {
    window.history.replaceState(null, "", "/workshop/rag/domains/demo/files?workspace=company&folder=b");
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
  await screen.findByRole("heading", { name: "B" });
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
  expect(invalidated).toHaveBeenCalledTimes(1);
  await act(async () => rejectPost(new DOMException("aborted", "AbortError")));
  expect(invalidated).toHaveBeenCalledTimes(1);
}, 15_000);
