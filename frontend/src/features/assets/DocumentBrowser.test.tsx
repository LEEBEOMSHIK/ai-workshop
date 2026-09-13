import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import type { DocumentSummary, LibraryPage } from "./api";
import { DocumentBrowser } from "./DocumentBrowser";
import { getWorkspaceCapabilities } from "../workspaces/api";

vi.mock("../workspaces/api", async (importOriginal) => ({
  ...await importOriginal<typeof import("../workspaces/api")>(),
  getWorkspaceCapabilities: vi.fn(async () => ({ read: true, write: true, delete: false, manage_members: false })),
}));

const document: DocumentSummary = {
  active_version_id: "version-2", folder_id: null, id: "document-1", job_id: null,
  latest_version: 3, latest_version_id: "version-3", metadata_revision: 1, name: "합성 문서.md",
  status: "processing", workspace_id: "workspace-1",
};

const root: LibraryPage = {
  ancestors: [], documents: [document], folder: null,
  folders: [{ id: "folder-1", metadata_revision: 1, name: "제품", parent_id: null, has_children: false }],
  next_document_cursor: null, next_folder_cursor: null,
  workspace: { id: "workspace-1", name: "제품 자료", kind: "company", expires_at: null },
};

const folderPage: LibraryPage = {
  ...root, ancestors: [], documents: [], folder: { id: "folder-1", metadata_revision: 1, name: "제품", parent_id: null }, folders: [],
};

function renderBrowser(options: Partial<Parameters<typeof DocumentBrowser>[0]> = {}) {
  return render(<DocumentBrowser workspaceId="workspace-1" initialLibrary={root} initialRoot={root}
    initialWorkspaces={[root.workspace, { id: "personal-1", name: "내 메모", kind: "personal", expires_at: null }]}
    initialDocument={null} initialVersionId={null} {...options} />);
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); window.history.replaceState(null, "", "/"); });

it("identifies the file cabinet and links back while retaining the current workspace", () => {
  renderBrowser();
  expect(screen.getByRole("heading", { level: 1, name: "제품 자료" })).toBeVisible();
  expect(screen.getByRole("link", { name: "파일함으로" })).toHaveAttribute("href", "/workshop/workspaces");
  expect(screen.getByText("FILE CABINET")).toBeVisible();
});

function stubRestoredViewer(selected: DocumentSummary, page: LibraryPage) {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.endsWith("/versions")) return Response.json({ items: [], next_cursor: null });
    if (path.endsWith("/preview")) {
      const previewDocument = path.includes(`/documents/${document.id}/`) ? document : selected;
      return Response.json({ asset_version_id: "version-2", document_id: previewDocument.id, kind: "text", name: previewDocument.name, page_count: null, size: 18, text: "복원한 원문", version: 2 });
    }
    if (path.endsWith(`/library/documents/${selected.id}`)) return Response.json(selected);
    if (path.endsWith("/library")) return Response.json(page);
    throw new Error(`Unexpected request: ${path}`);
  }));
}

it("returns focus to the rendered document when closing a reload-restored viewer", async () => {
  stubRestoredViewer(document, root);
  const user = userEvent.setup();
  renderBrowser({ initialDocument: document, initialVersionId: "version-2" });
  await screen.findByText("복원한 원문");

  await user.click(screen.getByRole("button", { name: "문서 닫기" }));

  expect(screen.getByRole("button", { name: "합성 문서.md 열기" })).toHaveFocus();
  expect(window.location.search).toBe("");
});

it("focuses the current folder heading when the restored document is outside the loaded page", async () => {
  stubRestoredViewer(document, root);
  const user = userEvent.setup();
  renderBrowser({ initialLibrary: { ...root, documents: [{ ...document, id: "other-document", name: "다른 문서.txt" }] }, initialDocument: document, initialVersionId: "version-2" });
  await screen.findByText("복원한 원문");

  await user.click(screen.getByRole("button", { name: "문서 닫기" }));

  expect(screen.getByRole("heading", { name: "파일함 최상위" })).toHaveFocus();
});

it("returns focus to the URL-restored document instead of an earlier clicked document", async () => {
  const restored = { ...document, id: "document-2", name: "복원 대상.txt" };
  const page = { ...root, documents: [document, restored] };
  stubRestoredViewer(restored, page);
  const user = userEvent.setup();
  renderBrowser({ initialLibrary: page });
  await user.click(screen.getByRole("button", { name: "합성 문서.md 열기" }));
  await screen.findByText("복원한 원문");
  window.history.replaceState(null, "", "/workshop/workspaces/workspace-1/documents?document=document-2&version=version-2");
  await act(async () => window.dispatchEvent(new PopStateEvent("popstate")));
  await screen.findByText("복원한 원문");

  await user.click(screen.getByRole("button", { name: "문서 닫기" }));

  expect(screen.getByRole("button", { name: "복원 대상.txt 열기" })).toHaveFocus();
});

it("selects a folder with a scoped GET and uploads to that exact folder without mutation during navigation", async () => {
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (init?.method === "POST") return Response.json({ ...document, folder_id: "folder-1" }, { status: 201 });
    if (path.includes("folder_id=folder-1")) return Response.json(folderPage);
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  renderBrowser();

  await user.click(screen.getByRole("button", { name: "제품 폴더 열기" }));
  expect(await screen.findByText("이 폴더에는 문서가 없습니다.")).toBeVisible();
  expect(fetcher.mock.calls[0][1]?.method).toBeUndefined();
  expect(window.location.search).toBe("?folder=folder-1");

  await user.upload(screen.getByLabelText("새 문서 파일"), new File(["text"], "new.txt", { type: "text/plain" }));
  const upload = fetcher.mock.calls.find(([, init]) => init?.method === "POST");
  expect(upload?.[0]).toBe("/api/v1/workspaces/workspace-1/documents");
  expect((upload?.[1]?.body as FormData).get("folder_id")).toBe("folder-1");
});

it("hides stale rows and mutation controls while folder navigation is pending", async () => {
  let resolveFolder!: (response: Response) => void;
  const pendingFolder = new Promise<Response>((resolve) => { resolveFolder = resolve; });
  const fetcher = vi.fn<typeof fetch>(() => pendingFolder);
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  renderBrowser();

  await user.click(screen.getByRole("button", { name: "제품 폴더 열기" }));

  expect(screen.queryByRole("button", { name: "합성 문서.md 열기" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "새 폴더" })).toBeDisabled();
  expect(screen.getByLabelText("새 문서 파일")).toBeDisabled();
  expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  await act(async () => resolveFolder(Response.json(folderPage)));
  expect(await screen.findByText("이 폴더에는 문서가 없습니다.")).toBeVisible();
});

it("keeps failed navigation inert and retries the exact attempted folder", async () => {
  let reads = 0;
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    reads += 1;
    expect(String(input)).toContain("folder_id=folder-1");
    return reads === 1
      ? Response.json({ error: { code: "temporary", message: "private", correlation_id: "synthetic" } }, { status: 500 })
      : Response.json(folderPage);
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  renderBrowser();

  await user.click(screen.getByRole("button", { name: "제품 폴더 열기" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("선택한 위치를 불러오지 못했습니다.");
  expect(screen.getByRole("button", { name: "새 폴더" })).toBeDisabled();
  expect(screen.getByLabelText("새 문서 파일")).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "다시 시도" }));
  expect(await screen.findByText("이 폴더에는 문서가 없습니다.")).toBeVisible();
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("opens the exact active version, distinguishes latest processing, and restores focus on close", async () => {
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.includes("/library/")) return Response.json({ items: [
      { id: "version-3", number: 3, media_type: "text/markdown", size: 20, status: "processing" },
      { id: "version-2", number: 2, media_type: "text/markdown", size: 18, status: "ready" },
    ], next_cursor: null });
    return Response.json({ asset_version_id: "version-2", document_id: "document-1", kind: "markdown", name: "합성 문서.md", page_count: null, size: 18, text: "합성 문서 본문", version: 2 });
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  renderBrowser();

  const opener = screen.getByRole("button", { name: "합성 문서.md 열기" });
  await user.click(opener);
  expect(await screen.findByText("합성 문서 본문")).toBeVisible();
  expect(screen.getByRole("button", { name: "버전 3 · 최신 · 처리 중" })).toBeDisabled();
  expect(window.location.search).toBe("?document=document-1&version=version-2");
  expect(fetcher.mock.calls.every(([, init]) => !init?.method || init.method === "GET")).toBe(true);
  await user.click(screen.getByRole("button", { name: "문서 닫기" }));
  expect(screen.getByRole("button", { name: "합성 문서.md 열기" })).toHaveFocus();
});

it("opens metadata for a document without an active READY original without claiming it is ready", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => Response.json({
    items: [{ id: "version-3", number: 3, media_type: "text/html", size: 20, status: "processing" }],
    next_cursor: null,
  })));
  const user = userEvent.setup();
  const unavailable = { ...document, active_version_id: null, name: "처리 중.html" };
  renderBrowser({ initialLibrary: { ...root, documents: [unavailable] } });

  const opener = screen.getByRole("button", { name: "처리 중.html 열기" });
  expect(opener).toBeEnabled();
  await user.click(opener);
  expect(await screen.findByText("열람할 수 있는 활성 원본 버전이 없습니다.")).toBeVisible();
  expect(screen.queryByText("원본 준비됨")).not.toBeInTheDocument();
});

it("creates a folder under the selected folder and refreshes that exact page", async () => {
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (init?.method === "POST") return Response.json({ id: "child-1", name: "회의", parent_id: "folder-1" }, { status: 201 });
    if (path.includes("folder_id=folder-1")) return Response.json(folderPage);
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  renderBrowser({ initialLibrary: folderPage });

  await user.click(screen.getByRole("button", { name: "새 폴더" }));
  await user.type(screen.getByRole("textbox", { name: "폴더 이름" }), "회의");
  await user.click(screen.getByRole("button", { name: "폴더 만들기" }));

  const create = fetcher.mock.calls.find(([, init]) => init?.method === "POST");
  expect(JSON.parse(create?.[1]?.body as string)).toEqual({ name: "회의", parent_id: "folder-1" });
  expect(fetcher.mock.calls.filter(([input]) => String(input).includes("folder_id=folder-1"))).toHaveLength(1);
  expect(screen.getByRole("button", { name: "회의 폴더 열기" })).toBeVisible();
});

it("keeps the existing new-version and duplicate upload behavior", async () => {
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    if (String(input).includes("document-1/versions")) return Response.json({ ...document, latest_version: 4, latest_version_id: "version-4" }, { status: 201 });
    return Response.json({ error: { code: "duplicate_document_content", message: "private detail", correlation_id: "synthetic" } }, { status: 409 });
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  renderBrowser();

  await waitFor(() => expect(screen.getByLabelText("합성 문서.md 새 버전 파일")).toBeEnabled());
  await user.upload(screen.getByLabelText("합성 문서.md 새 버전 파일"), new File(["v4"], "doc.md", { type: "text/markdown" }));
  expect(await screen.findByText("최신 버전 4")).toBeVisible();
  await user.upload(screen.getByLabelText("새 문서 파일"), new File(["duplicate"], "copy.md", { type: "text/markdown" }));
  expect(await screen.findByText("같은 내용의 문서가 이 지식 공간에 이미 있습니다.")).toBeVisible();
  expect(screen.queryByText("private detail")).not.toBeInTheDocument();
});

it("ignores a stale folder reply after the user changes scope", async () => {
  let resolveFirst!: (response: Response) => void;
  const first = new Promise<Response>((resolve) => { resolveFirst = resolve; });
  const secondPage = { ...root, folder: { id: "folder-2", metadata_revision: 1, name: "두 번째", parent_id: null }, folders: [], documents: [{ ...document, id: "document-2", name: "현재.txt" }] };
  vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => String(input).includes("folder-1") ? first : Promise.resolve(Response.json(secondPage))));
  const user = userEvent.setup();
  renderBrowser({ initialRoot: { ...root, folders: [...root.folders, { id: "folder-2", metadata_revision: 1, name: "두 번째", parent_id: null, has_children: false }] } });

  await user.click(screen.getByRole("button", { name: "제품 폴더 열기" }));
  await user.click(screen.getByRole("button", { name: "두 번째 폴더 열기" }));
  expect(await screen.findByRole("button", { name: "현재.txt 열기" })).toBeVisible();
  await act(async () => resolveFirst(Response.json({ ...folderPage, documents: [{ ...document, name: "늦은.txt" }] })));
  expect(screen.queryByRole("button", { name: "늦은.txt 열기" })).not.toBeInTheDocument();
});

it("restores an exact historical version from back navigation even when it is not on the first version page", async () => {
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.endsWith("/library/documents/document-1")) return Response.json({ ...document, folder_id: "folder-1" });
    if (path.includes("/library?folder_id=folder-1")) return Response.json({ ...folderPage, documents: [{ ...document, folder_id: "folder-1" }] });
    if (path.endsWith("/library/documents/document-1/versions")) return Response.json({
      items: [{ id: "version-3", number: 3, media_type: "text/markdown", size: 20, status: "processing" }],
      next_cursor: "more-versions",
    });
    if (path.endsWith("/versions/version-old/preview")) return Response.json({ asset_version_id: "version-old", document_id: "document-1", kind: "text", name: "합성 문서.md", page_count: null, size: 12, text: "과거 원문", version: 1 });
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  renderBrowser();

  window.history.replaceState(null, "", "/workshop/workspaces/workspace-1/documents?folder=folder-1&document=document-1&version=version-old");
  await act(async () => window.dispatchEvent(new PopStateEvent("popstate")));

  expect(await screen.findByText("과거 원문")).toBeVisible();
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/documents/document-1/versions/version-old/preview",
    expect.objectContaining({ credentials: "include", signal: expect.any(AbortSignal) }),
  );
});

it("fails closed for a contradictory folder and document URL without showing previous content", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
    if (String(input).endsWith("/library/documents/document-1")) return Response.json({ ...document, folder_id: "folder-1" });
    throw new Error(`Unexpected request: ${String(input)}`);
  }));
  renderBrowser();

  window.history.replaceState(null, "", "/workshop/workspaces/workspace-1/documents?folder=foreign-folder&document=document-1");
  await act(async () => window.dispatchEvent(new PopStateEvent("popstate")));

  expect(await screen.findByRole("alert")).toHaveTextContent("폴더와 문서 선택이 일치하지 않습니다.");
  expect(screen.queryByRole("button", { name: "합성 문서.md 열기" })).not.toBeInTheDocument();
});

it("fails closed before any GET when popstate contains a version without a document", async () => {
  const fetcher = vi.fn<typeof fetch>();
  vi.stubGlobal("fetch", fetcher);
  renderBrowser();

  window.history.replaceState(null, "", "/workshop/workspaces/workspace-1/documents?version=foreign-version");
  await act(async () => window.dispatchEvent(new PopStateEvent("popstate")));

  expect(await screen.findByRole("alert")).toHaveTextContent("문서 없는 버전 주소는 열 수 없습니다.");
  expect(screen.queryByRole("button", { name: "합성 문서.md 열기" })).not.toBeInTheDocument();
  expect(fetcher).not.toHaveBeenCalled();
});

it("ignores a late preview reply after switching to another READY version", async () => {
  let resolveOld!: (response: Response) => void;
  const oldPreview = new Promise<Response>((resolve) => { resolveOld = resolve; });
  vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => {
    const path = String(input);
    if (path.endsWith("/library/documents/document-1/versions")) return Promise.resolve(Response.json({ items: [
      { id: "version-2", number: 2, media_type: "text/markdown", size: 18, status: "ready" },
      { id: "version-1", number: 1, media_type: "text/markdown", size: 12, status: "ready" },
    ], next_cursor: null }));
    if (path.endsWith("/versions/version-2/preview")) return oldPreview;
    if (path.endsWith("/versions/version-1/preview")) return Promise.resolve(Response.json({ asset_version_id: "version-1", document_id: "document-1", kind: "text", name: "합성 문서.md", page_count: null, size: 12, text: "선택한 과거 원문", version: 1 }));
    throw new Error(`Unexpected request: ${path}`);
  }));
  const user = userEvent.setup();
  renderBrowser({ initialLibrary: { ...root, documents: [{ ...document, latest_version: 2, latest_version_id: "version-2", status: "ready" }] } });

  await user.click(screen.getByRole("button", { name: "합성 문서.md 열기" }));
  await user.click(await screen.findByRole("button", { name: "버전 1 · 원본 준비됨" }));
  expect(await screen.findByText("선택한 과거 원문")).toBeVisible();
  await act(async () => resolveOld(Response.json({ asset_version_id: "version-2", document_id: "document-1", kind: "text", name: "합성 문서.md", page_count: null, size: 18, text: "늦은 이전 원문", version: 2 })));
  expect(screen.queryByText("늦은 이전 원문")).not.toBeInTheDocument();
});

it("appends the next bounded document page for the current folder", async () => {
  const nextDocument = { ...document, id: "document-2", name: "다음.txt" };
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    expect(String(input)).toContain("document_cursor=next-documents");
    return Response.json({ ...root, documents: [nextDocument], next_document_cursor: null });
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  renderBrowser({ initialLibrary: { ...root, next_document_cursor: "next-documents" } });

  await user.click(screen.getByRole("button", { name: "문서 더 보기" }));
  expect(await screen.findByRole("button", { name: "다음.txt 열기" })).toBeVisible();
  expect(screen.getByRole("button", { name: "합성 문서.md 열기" })).toBeVisible();
});

it("consumes a document cursor only once during repeated activation", async () => {
  let resolvePage!: (response: Response) => void;
  const nextPage = new Promise<Response>((resolve) => { resolvePage = resolve; });
  const fetcher = vi.fn<typeof fetch>(() => nextPage);
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  renderBrowser({ initialLibrary: { ...root, next_document_cursor: "next-documents" } });

  const loadMore = screen.getByRole("button", { name: "문서 더 보기" });
  await user.click(loadMore);
  expect(loadMore).toBeDisabled();
  await user.click(loadMore);
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async () => resolvePage(Response.json({ ...root, documents: [{ ...document, id: "document-2", name: "한 번만.txt" }], next_document_cursor: null })));
  expect(await screen.findAllByRole("button", { name: "한 번만.txt 열기" })).toHaveLength(1);
});

it("does not append a late document page after navigating to another folder", async () => {
  let resolvePage!: (response: Response) => void;
  const oldPage = new Promise<Response>((resolve) => { resolvePage = resolve; });
  const currentPage = { ...root, folder: { id: "folder-2", metadata_revision: 1, name: "두 번째", parent_id: null }, folders: [], documents: [{ ...document, id: "current-document", name: "현재 범위.txt", folder_id: "folder-2" }], next_document_cursor: null };
  vi.stubGlobal("fetch", vi.fn<typeof fetch>((input) => String(input).includes("document_cursor=old-page")
    ? oldPage
    : Promise.resolve(Response.json(currentPage))));
  const user = userEvent.setup();
  renderBrowser({
    initialLibrary: { ...root, next_document_cursor: "old-page" },
    initialRoot: { ...root, folders: [...root.folders, { id: "folder-2", metadata_revision: 1, name: "두 번째", parent_id: null, has_children: false }] },
  });

  await user.click(screen.getByRole("button", { name: "문서 더 보기" }));
  await user.click(screen.getByRole("button", { name: "두 번째 폴더 열기" }));
  expect(await screen.findByRole("button", { name: "현재 범위.txt 열기" })).toBeVisible();
  await act(async () => resolvePage(Response.json({ ...root, documents: [{ ...document, id: "old-document", name: "이전 범위.txt" }], next_document_cursor: null })));
  expect(screen.queryByRole("button", { name: "이전 범위.txt 열기" })).not.toBeInTheDocument();
});

it("does not let a late post-upload refresh replace a newer folder selection", async () => {
  let resolveRefresh!: (response: Response) => void;
  let markRefreshStarted!: () => void;
  const refreshStarted = new Promise<void>((resolve) => { markRefreshStarted = resolve; });
  const oldRefresh = new Promise<Response>((resolve) => { resolveRefresh = resolve; });
  const currentPage = { ...root, folder: { id: "folder-2", metadata_revision: 1, name: "두 번째", parent_id: null }, folders: [], documents: [{ ...document, id: "current-document", name: "현재 범위.txt", folder_id: "folder-2" }] };
  const fetcher = vi.fn<typeof fetch>((input, init) => {
    const path = String(input);
    if (init?.method === "POST") return Promise.resolve(Response.json({ ...document, id: "uploaded-document", name: "업로드됨.txt" }, { status: 201 }));
    if (path.endsWith("/library")) { markRefreshStarted(); return oldRefresh; }
    if (path.includes("folder_id=folder-2")) return Promise.resolve(Response.json(currentPage));
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  renderBrowser({ initialRoot: { ...root, folders: [...root.folders, { id: "folder-2", metadata_revision: 1, name: "두 번째", parent_id: null, has_children: false }] } });

  await waitFor(() => expect(screen.getByLabelText("새 문서 파일")).toBeEnabled());
  await user.upload(screen.getByLabelText("새 문서 파일"), new File(["text"], "uploaded.txt", { type: "text/plain" }));
  await refreshStarted;
  await user.click(screen.getByRole("button", { name: "두 번째 폴더 열기" }));
  expect(await screen.findByRole("button", { name: "현재 범위.txt 열기" })).toBeVisible();
  await act(async () => resolveRefresh(Response.json({ ...root, documents: [{ ...document, id: "old-document", name: "이전 범위.txt" }] })));
  expect(screen.queryByText(/저장 완료/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "이전 범위.txt 열기" })).not.toBeInTheDocument();
});

it("retains the uploaded document job identity when reconciliation omits it", async () => {
  const uploaded = { ...document, id: "uploaded-document", name: "처리할 문서.txt", job_id: "job-upload-1", status: "stored" as const };
  const reconciled = { ...uploaded, job_id: null };
  const fetcher = vi.fn<typeof fetch>(async (_input, init) => init?.method === "POST"
    ? Response.json(uploaded, { status: 201 })
    : Response.json({ ...root, documents: [reconciled] }));
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  renderBrowser({ initialLibrary: { ...root, documents: [] } });

  await waitFor(() => expect(screen.getByLabelText("새 문서 파일")).toBeEnabled());
  await user.upload(screen.getByLabelText("새 문서 파일"), new File(["text"], "job.txt", { type: "text/plain" }));

  expect(await screen.findByRole("button", { name: "처리할 문서.txt 열기" })).toBeVisible();
  expect(screen.getByRole("button", { name: "상태 새로고침" })).toBeVisible();
  expect(screen.getByText("저장됨")).toBeVisible();
});

it("shows a committed folder after refresh failure and retries reconciliation without another POST", async () => {
  let reads = 0;
  const created = { id: "folder-new", name: "새 자료", parent_id: null };
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    if (init?.method === "POST") return Response.json(created, { status: 201 });
    reads += 1;
    if (reads === 1) return Response.json({ error: { code: "temporary", message: "private", correlation_id: "synthetic" } }, { status: 500 });
    return Response.json({ ...root, folders: [...root.folders, { ...created, has_children: false }] });
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  renderBrowser();

  await user.click(screen.getByRole("button", { name: "새 폴더" }));
  await user.type(screen.getByRole("textbox", { name: "폴더 이름" }), "새 자료");
  await user.click(screen.getByRole("button", { name: "폴더 만들기" }));

  expect(await screen.findByRole("button", { name: "새 자료 폴더 열기" })).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("폴더는 만들어졌지만 목록을 새로 맞추지 못했습니다.");
  expect(screen.queryByText("폴더를 만들지 못했습니다.", { exact: false })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "목록 다시 맞추기" }));
  expect(await screen.findByRole("button", { name: "새 자료 폴더 열기" })).toBeVisible();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});

it("supports an injected read-only document picker without exposing management actions", async () => {
  const browse = vi.fn(async () => folderPage);
  const getDocument = vi.fn(async () => document);
  const toggleSelection = vi.fn();
  const writeSelection = vi.fn();
  const user = userEvent.setup();

  renderBrowser({
    readOnly: true,
    browse,
    getDocument,
    selectedDocumentIds: new Set([document.id]),
    onToggleDocumentSelection: toggleSelection,
    writeSelection,
  });

  expect(screen.queryByRole("button", { name: "새 폴더" })).not.toBeInTheDocument();
  expect(screen.queryByLabelText("새 문서 파일")).not.toBeInTheDocument();
  expect(screen.queryByLabelText("합성 문서.md 새 버전 파일")).not.toBeInTheDocument();
  const checkbox = screen.getByRole("checkbox", { name: "합성 문서.md 선택" });
  expect(checkbox).toBeChecked();
  await user.click(checkbox);
  expect(toggleSelection).toHaveBeenCalledWith(document, false);

  await user.click(screen.getByRole("button", { name: "제품 폴더 열기" }));
  expect(browse).toHaveBeenCalledWith("workspace-1", expect.objectContaining({ folderId: "folder-1" }));
  expect(writeSelection).toHaveBeenCalledWith("workspace-1", { folderId: "folder-1", documentId: null, versionId: null });
  expect(getDocument).not.toHaveBeenCalled();
});

it("mounts workspace member management only when the caller explicitly enables it", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json({ read: true, write: true, delete: true, manage_members: true }));
  vi.stubGlobal("fetch", fetcher);

  const hidden = renderBrowser();
  await act(async () => undefined);
  expect(fetcher).not.toHaveBeenCalled();
  hidden.unmount();

  vi.mocked(getWorkspaceCapabilities).mockResolvedValue({ read: true, write: true, delete: true, manage_members: true });
  renderBrowser({ showMemberManagement: true });
  expect(await screen.findByRole("button", { name: "구성원 권한 관리" })).toBeVisible();
  expect(getWorkspaceCapabilities).toHaveBeenCalledWith("workspace-1", expect.any(AbortSignal));
});
