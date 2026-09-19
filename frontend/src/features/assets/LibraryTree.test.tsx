import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import type { LibraryPage } from "./api";
import { LibraryTree } from "./LibraryTree";

const root: LibraryPage = {
  ancestors: [],
  documents: [],
  folder: null,
  folders: [{ id: "folder-projects", metadata_revision: 1, name: "Projects", parent_id: null, has_children: true }],
  next_document_cursor: null,
  next_folder_cursor: "next-root",
  workspace: { id: "workspace-1", name: "제품 자료", kind: "company", expires_at: null },
};

afterEach(() => vi.unstubAllGlobals());

it("keeps the cabinet top level distinct from a real root folder during keyboard navigation", async () => {
  const user = userEvent.setup();
  const selectFolder = vi.fn();
  render(<LibraryTree workspaces={[root.workspace]} currentWorkspaceId="workspace-1" selectedFolderId={null}
    initialRoot={{ ...root, folders: [{ id: "named-root", metadata_revision: 1, name: "root", parent_id: null, has_children: false }] }} onSelectFolder={selectFolder} />);

  const topLevel = screen.getByRole("button", { name: "root" });
  expect(topLevel).toHaveAttribute("aria-current", "page");
  topLevel.focus();
  await user.keyboard("{Enter}");
  expect(selectFolder).toHaveBeenLastCalledWith(null);
  await user.tab();
  expect(screen.getByRole("button", { name: "root 폴더 열기" })).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(selectFolder).toHaveBeenLastCalledWith("named-root");
});

it("uses grouped workspace navigation and lazy nested folder disclosures", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json({
    ...root,
    folder: { id: "folder-projects", metadata_revision: 1, name: "Projects", parent_id: null },
    folders: [{ id: "folder-2026", metadata_revision: 1, name: "2026", parent_id: "folder-projects", has_children: false }],
    next_folder_cursor: null,
  }));
  vi.stubGlobal("fetch", fetcher);
  const selectFolder = vi.fn();
  const user = userEvent.setup();
  render(<LibraryTree
    workspaces={[
      root.workspace,
      { id: "workspace-2", name: "내 메모", kind: "personal", expires_at: null },
    ]}
    currentWorkspaceId="workspace-1"
    selectedFolderId={null}
    initialRoot={root}
    onSelectFolder={selectFolder}
  />);

  expect(screen.getByRole("heading", { name: "회사 공간" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "개인 공간" })).toBeVisible();
  expect(screen.getByRole("link", { name: "제품 자료" })).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("button", { name: "Projects 하위 폴더 펼치기" })).toHaveAttribute("aria-expanded", "false");

  await user.click(screen.getByRole("button", { name: "Projects 하위 폴더 펼치기" }));
  expect(await screen.findByRole("button", { name: "2026 폴더 열기" })).toBeVisible();
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/workspaces/workspace-1/library?folder_id=folder-projects",
    expect.objectContaining({ credentials: "include", signal: expect.any(AbortSignal) }),
  );
  await user.click(screen.getByRole("button", { name: "2026 폴더 열기" }));
  expect(selectFolder).toHaveBeenCalledWith("folder-2026");
});

it("loads the next bounded root folder page without replacing existing nodes", async () => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => Response.json({
    ...root,
    folders: [{ id: "folder-z", metadata_revision: 1, name: "Zeta", parent_id: null, has_children: false }],
    next_folder_cursor: null,
  })));
  const user = userEvent.setup();
  render(<LibraryTree workspaces={[root.workspace]} currentWorkspaceId="workspace-1" selectedFolderId={null} initialRoot={root} onSelectFolder={vi.fn()} />);

  await user.click(screen.getByRole("button", { name: "루트 폴더 더 보기" }));
  expect(screen.getByRole("button", { name: "Projects 폴더 열기" })).toBeVisible();
  expect(await screen.findByRole("button", { name: "Zeta 폴더 열기" })).toBeVisible();
});

it("starts collapsed at a narrow viewport and retains the selected folder when reopened", async () => {
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: true,
    media: "(max-width: 680px)",
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
  const user = userEvent.setup();
  render(<LibraryTree workspaces={[root.workspace]} currentWorkspaceId="workspace-1" selectedFolderId="folder-projects" initialRoot={root} onSelectFolder={vi.fn()} />);

  const toggle = screen.getByRole("button", { name: "폴더 탐색기 펼치기" });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByRole("button", { name: "Projects 폴더 열기" })).not.toBeInTheDocument();
  await user.click(toggle);
  expect(screen.getByRole("button", { name: "Projects 폴더 열기" })).toHaveAttribute("aria-current", "page");
  await user.click(screen.getByRole("button", { name: "폴더 탐색기 접기" }));
  await user.click(screen.getByRole("button", { name: "폴더 탐색기 펼치기" }));
  expect(screen.getByRole("button", { name: "Projects 폴더 열기" })).toHaveAttribute("aria-current", "page");
});

it("loads authoritative siblings and their next page when reopening a restored ancestor seed", async () => {
  const selected: LibraryPage = {
    ...root,
    ancestors: [{ id: "folder-a", metadata_revision: 1, name: "A", parent_id: null }],
    folder: { id: "folder-b", metadata_revision: 1, name: "B", parent_id: "folder-a" },
    folders: [],
    next_folder_cursor: null,
  };
  const restoredRoot = { ...root, folders: [{ id: "folder-a", metadata_revision: 1, name: "A", parent_id: null, has_children: true }], next_folder_cursor: null };
  const fetcher = vi.fn<typeof fetch>(async (input) => String(input).includes("folder_cursor=more-a")
    ? Response.json({ ...selected, folders: [{ id: "folder-d", metadata_revision: 1, name: "D", parent_id: "folder-a", has_children: false }], next_folder_cursor: null })
    : Response.json({ ...selected, folder: selected.ancestors[0], ancestors: [], folders: [
      { id: "folder-b", metadata_revision: 1, name: "B", parent_id: "folder-a", has_children: false },
      { id: "folder-c", metadata_revision: 1, name: "C", parent_id: "folder-a", has_children: false },
    ], next_folder_cursor: "more-a" }));
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<LibraryTree workspaces={[root.workspace]} currentWorkspaceId="workspace-1" selectedFolderId="folder-b" initialRoot={restoredRoot} initialSelection={selected} onSelectFolder={vi.fn()} />);

  await user.click(screen.getByRole("button", { name: "A 하위 폴더 접기" }));
  await user.click(screen.getByRole("button", { name: "A 하위 폴더 펼치기" }));
  expect(await screen.findByRole("button", { name: "C 폴더 열기" })).toBeVisible();
  expect(fetcher).toHaveBeenCalledWith(
    "/api/v1/workspaces/workspace-1/library?folder_id=folder-a",
    expect.objectContaining({ credentials: "include", signal: expect.any(AbortSignal) }),
  );
  await user.click(screen.getByRole("button", { name: "하위 폴더 더 보기" }));
  expect(await screen.findByRole("button", { name: "D 폴더 열기" })).toBeVisible();
});

it("consumes a root folder cursor only once during repeated activation", async () => {
  let resolvePage!: (response: Response) => void;
  const page = new Promise<Response>((resolve) => { resolvePage = resolve; });
  const fetcher = vi.fn<typeof fetch>(() => page);
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<LibraryTree workspaces={[root.workspace]} currentWorkspaceId="workspace-1" selectedFolderId={null} initialRoot={root} onSelectFolder={vi.fn()} />);

  const loadMore = screen.getByRole("button", { name: "루트 폴더 더 보기" });
  await user.click(loadMore);
  expect(loadMore).toBeDisabled();
  await user.click(loadMore);
  expect(fetcher).toHaveBeenCalledTimes(1);
  await act(async () => resolvePage(Response.json({ ...root, folders: [{ id: "folder-z", metadata_revision: 1, name: "Zeta", parent_id: null, has_children: false }], next_folder_cursor: null })));
  expect(await screen.findAllByRole("button", { name: "Zeta 폴더 열기" })).toHaveLength(1);
});

it("uses injected domain browsing and workspace navigation without Platform URLs", async () => {
  const browse = vi.fn(async () => ({
    ...root,
    folder: { id: "folder-projects", metadata_revision: 1, name: "Projects", parent_id: null },
    folders: [],
    next_folder_cursor: null,
  }));
  const selectWorkspace = vi.fn();
  const user = userEvent.setup();
  render(<LibraryTree
    workspaces={[root.workspace, { id: "workspace-2", name: "내 메모", kind: "personal", expires_at: null }]}
    currentWorkspaceId="workspace-1"
    selectedFolderId={null}
    initialRoot={root}
    onSelectFolder={vi.fn()}
    browse={browse}
    onSelectWorkspace={selectWorkspace}
  />);

  await user.click(screen.getByRole("button", { name: "내 메모" }));
  expect(selectWorkspace).toHaveBeenCalledWith("workspace-2");
  expect(screen.queryByRole("link", { name: "내 메모" })).not.toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Projects 하위 폴더 펼치기" }));
  expect(browse).toHaveBeenCalledWith("workspace-1", expect.objectContaining({ folderId: "folder-projects" }));
});

it("disables folder choices outside an injected fixed selection boundary", () => {
  render(<LibraryTree
    workspaces={[root.workspace]}
    currentWorkspaceId="workspace-1"
    selectedFolderId="folder-allowed"
    initialRoot={{ ...root, folders: [
      { id: "folder-allowed", metadata_revision: 1, name: "Allowed", parent_id: null, has_children: false },
      { id: "folder-other", metadata_revision: 1, name: "Other", parent_id: null, has_children: false },
    ] }}
    onSelectFolder={vi.fn()}
    isFolderSelectionDisabled={(folderId) => folderId !== "folder-allowed"}
  />);

  expect(screen.getByRole("button", { name: "root" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "Allowed 폴더 열기" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "Other 폴더 열기" })).toBeDisabled();
});
