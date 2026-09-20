import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import type { LibraryPage } from "../../assets/api";
import { ragDomainChatPath } from "../../../shared/routing/routes";
import type { DomainLibraryContext } from "./library-api";
import { DomainFileCabinet } from "./DomainFileCabinet";

const push = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));

const company = { id: "11111111-1111-4111-8111-111111111111", name: "회사 규정", kind: "company", expires_at: null } as const;
const personal = { id: "22222222-2222-4222-8222-222222222222", name: "개인 연구", kind: "personal", expires_at: null } as const;
const first = { active_version_id: "version-1", folder_id: null, id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", job_id: null, latest_version: 1, latest_version_id: "version-1", metadata_revision: 1, name: "운용 규정.md", status: "ready", workspace_id: company.id } as const;
const second = { ...first, id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", name: "리스크 메모.txt" };
const third = { ...first, id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", name: "초과 문서.txt" };
const root: LibraryPage = { ancestors: [], documents: [first], folder: null, folders: [], next_document_cursor: "next", next_folder_cursor: null, workspace: company };
const context: DomainLibraryContext = { domain_id: "domain-1", display_name: "자산운용", connection_version_id: "connection-1", workspace_options: [company, personal], selection_limit: 2 };

const writeCapabilities = { read: true, write: true, delete: false, manage_members: false };

it("uploads inside the standalone selected folder without applying selection, opening the upload or changing URL", async () => {
  const folder = { id: "risk", metadata_revision: 1, name: "위험 자료", parent_id: null, has_children: false };
  const original = { ...first, folder_id: folder.id };
  const page = { ...root, folder, documents: [original], next_document_cursor: null };
  const uploaded = { ...second, name: "새 자료.txt", folder_id: folder.id, status: "stored", active_version_id: null };
  let committed = false;
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json(writeCapabilities);
    if (init?.method === "POST") { committed = true; return Response.json(uploaded); }
    if (path.includes("/rag/domains/asset-management/library/") && path.includes("folder_id=risk")) return Response.json({ ...page, documents: committed ? [original, uploaded] : [original] });
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const apply = vi.fn(); const user = userEvent.setup(); const url = window.location.href;
  render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={page} initialRoot={{ ...root, folders: [folder] }} initialDocument={null} initialVersionId={null} initialSelectedDocuments={[original]} onApplySelection={apply} allowedFolderIdsByWorkspace={{ [company.id]: [folder.id] }} />);
  await waitFor(() => expect(screen.getByRole("button", { name: "문서 올리기" })).toBeEnabled());
  expect(screen.getByText(/저장 위치:/)).toHaveTextContent("회사 공간 / 회사 규정 / 위험 자료");
  await user.upload(screen.getByLabelText("새 문서 파일"), new File(["synthetic"], "new.txt", { type: "text/plain" }));
  expect(await screen.findByRole("button", { name: "새 자료.txt 열기" })).toBeVisible();
  expect(screen.getByRole("checkbox", { name: `${first.name} 선택` })).toBeChecked();
  expect(screen.getByRole("checkbox", { name: "새 자료.txt 선택" })).not.toBeChecked();
  expect(apply).not.toHaveBeenCalled(); expect(push).not.toHaveBeenCalled(); expect(window.location.href).toBe(url);
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  const post = fetcher.mock.calls.find(([, init]) => init?.method === "POST");
  expect(post?.[0]).toBe(`/api/v1/workspaces/${company.id}/documents`);
  expect((post?.[1]?.body as FormData).get("folder_id")).toBe("risk");
});

it("denies domain preflight without sending a Platform upload and invalidates the search draft", async () => {
  const fetcher = vi.fn(async (input: RequestInfo | URL) => String(input).endsWith("/capabilities") ? Response.json(writeCapabilities) : Response.json({ error: { code: "not_found", message: "private", correlation_id: "test" } }, { status: 404 }));
  vi.stubGlobal("fetch", fetcher); const user = userEvent.setup();
  render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={root} initialRoot={root} initialDocument={null} initialVersionId={null} initialSelectedDocuments={[first]} />);
  await waitFor(() => expect(screen.getByLabelText("새 문서 파일")).toBeEnabled());
  await user.upload(screen.getByLabelText("새 문서 파일"), new File(["synthetic"], "new.txt", { type: "text/plain" }));
  expect(await screen.findByText(/파일함 권한 또는 도메인 연결이 변경되었습니다/)).toBeVisible();
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
  expect(fetcher.mock.calls.every(([input]) => String(input).endsWith("/capabilities") || String(input).includes("/rag/domains/"))).toBe(true);
  expect(screen.queryByLabelText("새 문서 파일")).not.toBeInTheDocument();
});

it("ignores a late committed upload after switching workspace and clears retry state", async () => {
  let resolveUpload!: (value: Response) => void;
  const personalRoot = { ...root, workspace: personal, documents: [], next_document_cursor: null };
  const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json(writeCapabilities);
    if (init?.method === "POST") return new Promise<Response>((resolve) => { resolveUpload = resolve; });
    if (path.endsWith(`/workspaces/${personal.id}`)) return Response.json(personalRoot);
    if (path.endsWith(`/workspaces/${company.id}`)) return Response.json(root);
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetcher); const user = userEvent.setup(); const apply = vi.fn();
  render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={root} initialRoot={root} initialDocument={null} initialVersionId={null} initialSelectedDocuments={[first]} onApplySelection={apply} />);
  await waitFor(() => expect(screen.getByLabelText("새 문서 파일")).toBeEnabled());
  await user.upload(screen.getByLabelText("새 문서 파일"), new File(["synthetic"], "new.txt", { type: "text/plain" }));
  await user.click(screen.getByRole("button", { name: personal.name }));
  await screen.findByRole("heading", { name: personal.name });
  await act(async () => resolveUpload(Response.json({ ...second, name: "늦은 업로드.txt" })));
  expect(screen.queryByRole("button", { name: "늦은 업로드.txt 열기" })).not.toBeInTheDocument();
  expect(screen.queryByText(/저장 완료/)).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "업로드 다시 시도" })).not.toBeInTheDocument();
  expect(screen.getByText("1 / 2개 선택")).toBeVisible(); expect(apply).not.toHaveBeenCalled();
});

it("ignores denied preflight from an unmounted workspace without invalidating the new workspace selection", async () => {
  let rejectPreflight!: (response: Response) => void;
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/capabilities")) return Response.json(writeCapabilities);
    if (path.endsWith(`/workspaces/${company.id}`)) return new Promise<Response>((resolve) => { rejectPreflight = resolve; });
    if (path.endsWith(`/workspaces/${personal.id}`)) return Response.json({ ...root, workspace: personal, documents: [], next_document_cursor: null });
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetcher); const user = userEvent.setup();
  render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={root} initialRoot={root} initialDocument={null} initialVersionId={null} initialSelectedDocuments={[first]} />);
  await waitFor(() => expect(screen.getByLabelText("새 문서 파일")).toBeEnabled());
  await user.upload(screen.getByLabelText("새 문서 파일"), new File(["synthetic"], "new.txt", { type: "text/plain" }));
  await user.click(screen.getByRole("button", { name: personal.name }));
  await screen.findByRole("heading", { name: personal.name });
  await act(async () => rejectPreflight(Response.json({ error: { code: "not_found", message: "private", correlation_id: "test" } }, { status: 404 })));
  expect(screen.getByText("1 / 2개 선택")).toBeVisible();
  expect(screen.queryByText(/파일함 권한 또는 도메인 연결이 변경되었습니다/)).not.toBeInTheDocument();
});

beforeEach(() => {
  push.mockReset();
  window.history.replaceState(null, "", "/workshop/rag/domains/asset-management/files?workspace=11111111-1111-4111-8111-111111111111");
});

it("keeps selected documents across pages and sends only bounded UUID pairs to same-domain chat", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input) => {
    const path = String(input);
    if (path.includes("document_cursor=next")) return Response.json({ ...root, documents: [second, third], next_document_cursor: null });
    throw new Error(`Unexpected request: ${path}`);
  }));
  const user = userEvent.setup();
  render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={root} initialRoot={root} initialDocument={null} initialVersionId={null} />);

  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
  await user.click(screen.getByRole("checkbox", { name: "운용 규정.md 선택" }));
  await user.click(screen.getByRole("button", { name: "문서 더 보기" }));
  expect(await screen.findByRole("checkbox", { name: "리스크 메모.txt 선택" })).toBeVisible();
  expect(screen.getByRole("checkbox", { name: "운용 규정.md 선택" })).toBeChecked();
  await user.click(screen.getByRole("checkbox", { name: "리스크 메모.txt 선택" }));
  expect(screen.getByRole("checkbox", { name: "초과 문서.txt 선택" })).toBeDisabled();
  expect(screen.getByText("2 / 2개 선택")).toBeVisible();

  await user.click(screen.getByRole("button", { name: "선택 문서로 대화" }));
  expect(push).toHaveBeenCalledWith(ragDomainChatPath("asset-management", [
    { workspaceId: company.id, documentId: first.id },
    { workspaceId: company.id, documentId: second.id },
  ]));
  expect(push.mock.calls[0][0]).not.toContain("운용");
});

it("keeps workspace navigation inside the domain and invalidates selection after an authorization failure", async () => {
  const fetcher = vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path === `/api/v1/workspaces/${company.id}/capabilities`) return Response.json({ read: true, write: false, delete: false, manage_members: false });
    if (path.includes(`/workspaces/${personal.id}`)) return Response.json({ error: { code: "not_found", message: "private", correlation_id: "synthetic" } }, { status: 404 });
    throw new Error(`Unexpected request: ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={root} initialRoot={root} initialDocument={null} initialVersionId={null} />);

  await user.click(screen.getByRole("checkbox", { name: "운용 규정.md 선택" }));
  await user.click(screen.getByRole("button", { name: "개인 연구" }));

  expect(await screen.findByText(/파일함 권한 또는 도메인 연결이 변경되었습니다/)).toBeVisible();
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
  expect(fetcher).toHaveBeenCalledWith(
    `/api/v1/rag/domains/asset-management/library/workspaces/${personal.id}`,
    expect.objectContaining({ credentials: "include" }),
  );
  expect(fetcher).toHaveBeenCalledWith(
    `/api/v1/workspaces/${company.id}/capabilities`,
    expect.objectContaining({ credentials: "include" }),
  );
  expect(fetcher.mock.calls.some(([input]) => {
    const path = String(input);
    return path.startsWith("/api/v1/workspaces/") && !path.endsWith("/capabilities");
  })).toBe(false);
});

it("restores another authorized workspace from Back without escaping the domain route", async () => {
  const personalRoot = { ...root, documents: [], next_document_cursor: null, workspace: personal };
  vi.stubGlobal("fetch", vi.fn(async (input) => {
    if (String(input).includes(`/workspaces/${personal.id}`)) return Response.json(personalRoot);
    throw new Error(`Unexpected request: ${String(input)}`);
  }));
  render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={root} initialRoot={root} initialDocument={null} initialVersionId={null} />);

  window.history.replaceState(null, "", `/workshop/rag/domains/asset-management/files?workspace=${personal.id}`);
  await act(async () => window.dispatchEvent(new PopStateEvent("popstate")));

  expect(await screen.findByRole("heading", { name: "개인 연구" })).toBeVisible();
  expect(window.location.pathname).toBe("/workshop/rag/domains/asset-management/files");
});

it("ignores a late workspace response after a newer workspace choice", async () => {
  let resolvePersonal!: (response: Response) => void;
  const personalResponse = new Promise<Response>((resolve) => { resolvePersonal = resolve; });
  const personalRoot = { ...root, documents: [], next_document_cursor: null, workspace: personal };
  vi.stubGlobal("fetch", vi.fn(async (input) => {
    const path = String(input);
    if (path.includes(`/workspaces/${personal.id}`)) return personalResponse;
    if (path.includes(`/workspaces/${company.id}`)) return Response.json(root);
    throw new Error(`Unexpected request: ${path}`);
  }));
  const user = userEvent.setup();
  render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={root} initialRoot={root} initialDocument={null} initialVersionId={null} />);

  await user.click(screen.getByRole("button", { name: personal.name }));
  await user.click(screen.getAllByRole("button", { name: company.name })[0]);
  expect(await screen.findByRole("heading", { name: company.name })).toBeVisible();

  await act(async () => resolvePersonal(Response.json(personalRoot)));
  expect(screen.getByRole("heading", { name: company.name })).toBeVisible();
});

it("invalidates and disables a stale selection after a same-workspace authorization failure", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input) => {
    if (String(input).includes("document_cursor=next")) return Response.json({ error: { code: "forbidden", message: "private", correlation_id: "synthetic" } }, { status: 403 });
    throw new Error(`Unexpected request: ${String(input)}`);
  }));
  const user = userEvent.setup();
  render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={root} initialRoot={root} initialDocument={null} initialVersionId={null} />);

  const checkbox = screen.getByRole("checkbox", { name: `${first.name} 선택` });
  await user.click(checkbox);
  await user.click(screen.getByRole("button", { name: "문서 더 보기" }));

  expect(await screen.findByText(/파일함 권한 또는 도메인 연결이 변경되었습니다/)).toBeVisible();
  expect(checkbox).toBeDisabled();
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
});

it("keeps the authorization invalidation explanation visible after a later successful workspace load", async () => {
  const personalRoot = { ...root, documents: [], next_document_cursor: null, workspace: personal };
  vi.stubGlobal("fetch", vi.fn(async (input) => {
    const path = String(input);
    if (path.includes("document_cursor=next")) return Response.json({ error: { code: "forbidden", message: "private", correlation_id: "synthetic" } }, { status: 403 });
    if (path.includes(`/workspaces/${personal.id}`)) return Response.json(personalRoot);
    throw new Error(`Unexpected request: ${path}`);
  }));
  const user = userEvent.setup();
  render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={root} initialRoot={root} initialDocument={null} initialVersionId={null} />);

  await user.click(screen.getByRole("button", { name: "문서 더 보기" }));
  expect(await screen.findByText("파일함 권한 또는 도메인 연결이 변경되었습니다. 도메인을 다시 선택해 주세요.")).toBeVisible();
  await user.click(screen.getByRole("button", { name: personal.name }));

  expect(await screen.findByRole("heading", { name: personal.name })).toBeVisible();
  expect(screen.getByText("파일함 권한 또는 도메인 연결이 변경되었습니다. 도메인을 다시 선택해 주세요.")).toBeVisible();
});

it("invalidates selection when exact-document restoration loses authorization", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input) => {
    if (String(input).includes(`/documents/${second.id}`)) return Response.json({ error: { code: "not_found", message: "private", correlation_id: "synthetic" } }, { status: 404 });
    throw new Error(`Unexpected request: ${String(input)}`);
  }));
  const user = userEvent.setup();
  render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={root} initialRoot={root} initialDocument={null} initialVersionId={null} />);
  await user.click(screen.getByRole("checkbox", { name: `${first.name} 선택` }));

  window.history.replaceState(null, "", `/workshop/rag/domains/asset-management/files?workspace=${company.id}&document=${second.id}`);
  await act(async () => window.dispatchEvent(new PopStateEvent("popstate")));

  expect(await screen.findByText(/파일함 권한 또는 도메인 연결이 변경되었습니다/)).toBeVisible();
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
});

it("invalidates selected documents when the domain connection identity changes", async () => {
  const user = userEvent.setup();
  const { rerender } = render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={root} initialRoot={root} initialDocument={null} initialVersionId={null} />);
  await user.click(screen.getByRole("checkbox", { name: `${first.name} 선택` }));

  rerender(<DomainFileCabinet slug="asset-management" context={{ ...context, connection_version_id: "connection-2" }} initialLibrary={root} initialRoot={root} initialDocument={null} initialVersionId={null} />);

  expect(await screen.findByRole("alert")).toHaveTextContent("파일함 권한 또는 도메인 연결이 변경되었습니다");
  expect(screen.getByRole("checkbox", { name: `${first.name} 선택` })).toBeDisabled();
  expect(screen.getByRole("button", { name: "선택 문서로 대화" })).toBeDisabled();
});

it("resets the actual browser and closes its viewer when the active workspace is selected", async () => {
  const folder = { id: "folder-1", metadata_revision: 1, name: "리스크", parent_id: null, has_children: false };
  const folderDocument = { ...first, id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd", name: "폴더 문서.txt", folder_id: folder.id };
  const rootWithFolder = { ...root, folders: [folder], next_document_cursor: null };
  const folderPage = { ...rootWithFolder, ancestors: [], folder, folders: [], documents: [folderDocument] };
  vi.stubGlobal("fetch", vi.fn(async (input) => {
    const path = String(input);
    if (path.includes("folder_id=folder-1")) return Response.json(folderPage);
    if (path.endsWith(`/workspaces/${company.id}`)) return Response.json(rootWithFolder);
    if (path.endsWith(`/documents/${folderDocument.id}/versions`)) return Response.json({ items: [], next_cursor: null });
    throw new Error(`Unexpected request: ${path}`);
  }));
  const user = userEvent.setup();
  render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={rootWithFolder} initialRoot={rootWithFolder} initialDocument={null} initialVersionId={null} />);

  await user.click(screen.getByRole("button", { name: "리스크 폴더 열기" }));
  await user.click(await screen.findByRole("button", { name: "폴더 문서.txt 열기" }));
  expect(await screen.findByRole("complementary")).toBeVisible();
  await user.click(screen.getAllByRole("button", { name: company.name })[0]);

  expect(await screen.findByRole("button", { name: `${first.name} 열기` })).toBeVisible();
  expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
  expect(window.location.search).toBe(`?workspace=${company.id}`);
});

it("restores the canonical first workspace when Back reaches the bare file URL", async () => {
  const personalRoot = { ...root, documents: [], next_document_cursor: null, workspace: personal };
  vi.stubGlobal("fetch", vi.fn(async (input) => {
    const path = String(input);
    if (path.includes(`/workspaces/${personal.id}`)) return Response.json(personalRoot);
    if (path.includes(`/workspaces/${company.id}`)) return Response.json(root);
    throw new Error(`Unexpected request: ${path}`);
  }));
  window.history.replaceState(null, "", "/workshop/rag/domains/asset-management/files");
  const user = userEvent.setup();
  render(<DomainFileCabinet slug="asset-management" context={context} initialLibrary={root} initialRoot={root} initialDocument={null} initialVersionId={null} />);
  await user.click(screen.getByRole("button", { name: personal.name }));
  expect(await screen.findByRole("heading", { name: personal.name })).toBeVisible();

  window.history.replaceState(null, "", "/workshop/rag/domains/asset-management/files");
  await act(async () => window.dispatchEvent(new PopStateEvent("popstate")));

  expect(await screen.findByRole("heading", { name: company.name })).toBeVisible();
  expect(window.location.pathname).toBe("/workshop/rag/domains/asset-management/files");
});
