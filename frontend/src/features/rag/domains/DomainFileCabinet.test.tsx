import { act, render, screen } from "@testing-library/react";
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
const first = { active_version_id: "version-1", folder_id: null, id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", job_id: null, latest_version: 1, latest_version_id: "version-1", name: "운용 규정.md", status: "ready", workspace_id: company.id } as const;
const second = { ...first, id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", name: "리스크 메모.txt" };
const third = { ...first, id: "cccccccc-cccc-4ccc-8ccc-cccccccccccc", name: "초과 문서.txt" };
const root: LibraryPage = { ancestors: [], documents: [first], folder: null, folders: [], next_document_cursor: "next", next_folder_cursor: null, workspace: company };
const context: DomainLibraryContext = { domain_id: "domain-1", display_name: "자산운용", connection_version_id: "connection-1", workspace_options: [company, personal], selection_limit: 2 };

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
  expect(fetcher.mock.calls.some(([input]) => String(input).startsWith("/api/v1/workspaces/"))).toBe(false);
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
  const folder = { id: "folder-1", name: "리스크", parent_id: null, has_children: false };
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
