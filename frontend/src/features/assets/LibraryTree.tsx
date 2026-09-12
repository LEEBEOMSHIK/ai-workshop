"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState, useSyncExternalStore } from "react";

import { workspaceDocumentPath } from "../../shared/routing/routes";
import type { WorkspaceSummary } from "../workspaces/api";
import { browseLibrary, type LibraryFolder, type LibraryPage } from "./api";
import styles from "./DocumentLibrary.module.css";

interface Branch {
  authoritative: boolean;
  folders: LibraryFolder[];
  nextCursor: string | null;
  expanded: boolean;
  loading: boolean;
  error: boolean;
}

interface LibraryTreeProps {
  workspaces: WorkspaceSummary[];
  currentWorkspaceId: string;
  selectedFolderId: string | null;
  initialRoot: LibraryPage;
  initialSelection?: LibraryPage;
  onSelectFolder: (folderId: string | null) => void;
  browse?: typeof browseLibrary;
  onSelectWorkspace?: (workspaceId: string) => void;
  isFolderSelectionDisabled?: (folderId: string | null) => boolean;
}

const workspaceGroups: { label: string; kinds: WorkspaceSummary["kind"][] }[] = [
  { label: "회사 공간", kinds: ["company", "team"] },
  { label: "개인 공간", kinds: ["personal"] },
  { label: "임시 공간", kinds: ["temporary"] },
];

const narrowTreeQuery = "(max-width: 680px)";

export function LibraryTree({ workspaces, currentWorkspaceId, selectedFolderId, initialRoot, initialSelection = initialRoot, onSelectFolder, browse = browseLibrary, onSelectWorkspace, isFolderSelectionDisabled }: LibraryTreeProps) {
  const initialTree = buildInitialTree(initialRoot, initialSelection);
  const [root, setRoot] = useState<Branch>(() => initialTree.root);
  const [branches, setBranches] = useState<Record<string, Branch>>(() => initialTree.branches);
  const [openOverride, setOpenOverride] = useState<boolean | null>(null);
  const controllers = useRef(new Set<AbortController>());
  const cursorRequests = useRef(new Set<string>());
  const contentId = useId();
  const narrow = useSyncExternalStore(subscribeNarrowTree, isNarrowTree, () => false);
  const treeOpen = openOverride ?? !narrow;

  useEffect(() => () => {
    controllers.current.forEach((controller) => controller.abort());
  }, []);

  async function loadBranch(folderId: string, cursor: string | null = null) {
    const requestKey = `${folderId}:${cursor ?? "first"}`;
    if (cursorRequests.current.has(requestKey)) return;
    cursorRequests.current.add(requestKey);
    const existing = branches[folderId];
    setBranches((current) => ({ ...current, [folderId]: { ...(current[folderId] ?? emptyBranch()), expanded: true, loading: true, error: false } }));
    const controller = new AbortController();
    controllers.current.add(controller);
    try {
      const page = await browse(currentWorkspaceId, { folderId, folderCursor: cursor, signal: controller.signal });
      setBranches((current) => ({
        ...current,
        [folderId]: {
          authoritative: true,
          folders: cursor ? mergeFolders(current[folderId]?.folders ?? [], page.folders) : page.folders,
          nextCursor: page.next_folder_cursor,
          expanded: true,
          loading: false,
          error: false,
        },
      }));
    } catch (failure) {
      if (!isAbort(failure)) setBranches((current) => ({ ...current, [folderId]: { ...(current[folderId] ?? existing ?? emptyBranch()), expanded: true, loading: false, error: true } }));
    } finally {
      controllers.current.delete(controller);
      cursorRequests.current.delete(requestKey);
    }
  }

  function toggle(folder: LibraryFolder) {
    const branch = branches[folder.id];
    if (!branch) {
      void loadBranch(folder.id);
      return;
    }
    if (branch.expanded) {
      setBranches((current) => ({ ...current, [folder.id]: { ...branch, expanded: false } }));
      return;
    }
    if (!branch.authoritative) {
      void loadBranch(folder.id);
      return;
    }
    setBranches((current) => ({ ...current, [folder.id]: { ...branch, expanded: !branch.expanded } }));
  }

  async function loadMoreRoot() {
    const cursor = root.nextCursor;
    if (!cursor) return;
    const requestKey = `root:${cursor}`;
    if (cursorRequests.current.has(requestKey)) return;
    cursorRequests.current.add(requestKey);
    const controller = new AbortController();
    controllers.current.add(controller);
    setRoot((current) => ({ ...current, loading: true, error: false }));
    try {
      const page = await browse(currentWorkspaceId, { folderCursor: cursor, signal: controller.signal });
      setRoot((current) => current.nextCursor === cursor
        ? { ...current, folders: mergeFolders(current.folders, page.folders), nextCursor: page.next_folder_cursor, loading: false }
        : current);
    } catch (failure) {
      if (!isAbort(failure)) setRoot((current) => ({ ...current, loading: false, error: true }));
    } finally {
      controllers.current.delete(controller);
      cursorRequests.current.delete(requestKey);
    }
  }

  return <nav className={styles.tree} aria-label="파일 탐색기">
    <div className={styles.treeHeader}>
      <h2>지식 공간</h2>
      <button className={styles.treeToggle} type="button" aria-expanded={treeOpen} aria-controls={contentId} onClick={() => setOpenOverride(!treeOpen)}>
        폴더 탐색기 {treeOpen ? "접기" : "펼치기"}
      </button>
    </div>
    <div id={contentId} hidden={!treeOpen}>
      {workspaceGroups.map((group) => {
      const items = workspaces.filter((workspace) => group.kinds.includes(workspace.kind));
      if (!items.length) return null;
      return <section className={styles.treeGroup} key={group.label}>
        <h3>{group.label}</h3>
        <ul>{items.map((workspace) => <li key={workspace.id}>
          {onSelectWorkspace ? <button className={styles.workspaceLink} type="button" aria-current={workspace.id === currentWorkspaceId ? "page" : undefined} onClick={() => onSelectWorkspace(workspace.id)}>{workspace.name}</button> : <Link className={styles.workspaceLink} aria-current={workspace.id === currentWorkspaceId ? "page" : undefined} href={workspaceDocumentPath(workspace.id)}>{workspace.name}</Link>}
        </li>)}</ul>
      </section>;
      })}
      <section className={styles.treeGroup}>
        <h3>폴더</h3>
        <button type="button" disabled={isFolderSelectionDisabled?.(null) ?? false} aria-current={selectedFolderId === null ? "page" : undefined} onClick={() => onSelectFolder(null)}>루트 (미분류)</button>
        <ul>{root.folders.map((folder) => <FolderNode key={folder.id} folder={folder} depth={0} branches={branches} selectedFolderId={selectedFolderId} onSelect={onSelectFolder} onToggle={toggle} onLoadMore={loadBranch} isFolderSelectionDisabled={isFolderSelectionDisabled} />)}</ul>
        {root.loading ? <p role="status">폴더를 불러오는 중…</p> : null}
        {root.error ? <button type="button" onClick={loadMoreRoot}>루트 폴더 다시 시도</button> : null}
        {root.nextCursor && !root.error ? <button type="button" disabled={root.loading} onClick={loadMoreRoot}>루트 폴더 더 보기</button> : null}
      </section>
    </div>
  </nav>;
}

function FolderNode({ folder, depth, branches, selectedFolderId, onSelect, onToggle, onLoadMore, isFolderSelectionDisabled }: {
  folder: LibraryFolder;
  depth: number;
  branches: Record<string, Branch>;
  selectedFolderId: string | null;
  onSelect: (folderId: string) => void;
  onToggle: (folder: LibraryFolder) => void;
  onLoadMore: (folderId: string, cursor: string | null) => void;
  isFolderSelectionDisabled?: (folderId: string | null) => boolean;
}) {
  const branch = branches[folder.id];
  const expanded = branch?.expanded ?? false;
  return <li>
    <div className={styles.folderRow} style={{ paddingLeft: `${depth * 0.75}rem` }}>
      {folder.has_children ? <button type="button" aria-expanded={expanded} aria-label={`${folder.name} 하위 폴더 ${expanded ? "접기" : "펼치기"}`} onClick={() => onToggle(folder)}>{expanded ? "▾" : "▸"}</button> : <span aria-hidden="true" />}
      <button type="button" disabled={isFolderSelectionDisabled?.(folder.id) ?? false} aria-current={selectedFolderId === folder.id ? "page" : undefined} aria-label={`${folder.name} 폴더 열기`} onClick={() => onSelect(folder.id)}>{folder.name}</button>
    </div>
    {expanded ? <div>
      {branch?.loading ? <p role="status">하위 폴더를 불러오는 중…</p> : null}
      {branch?.error ? <button type="button" onClick={() => onLoadMore(folder.id, null)}>하위 폴더 다시 시도</button> : null}
      <ul>{branch?.folders.map((child) => <FolderNode key={child.id} folder={child} depth={depth + 1} branches={branches} selectedFolderId={selectedFolderId} onSelect={onSelect} onToggle={onToggle} onLoadMore={onLoadMore} isFolderSelectionDisabled={isFolderSelectionDisabled} />)}</ul>
      {branch?.nextCursor && !branch.error ? <button type="button" disabled={branch.loading} onClick={() => onLoadMore(folder.id, branch.nextCursor)}>하위 폴더 더 보기</button> : null}
    </div> : null}
  </li>;
}

function branchFromPage(page: LibraryPage, expanded: boolean): Branch {
  return { authoritative: true, folders: page.folders, nextCursor: page.next_folder_cursor, expanded, loading: false, error: false };
}

function buildInitialTree(initialRoot: LibraryPage, selection: LibraryPage): { root: Branch; branches: Record<string, Branch> } {
  const path = [...selection.ancestors, ...(selection.folder ? [selection.folder] : [])];
  const pathFolders: LibraryFolder[] = path.map((folder, index) => ({
    ...folder,
    has_children: index < path.length - 1 || (index === path.length - 1 && (selection.folders.length > 0 || selection.next_folder_cursor !== null)),
  }));
  const root = branchFromPage({ ...initialRoot, folders: mergeFolders(initialRoot.folders, pathFolders.slice(0, 1)) }, true);
  const branches: Record<string, Branch> = {};
  pathFolders.forEach((folder, index) => {
    branches[folder.id] = index === pathFolders.length - 1
      ? branchFromPage(selection, true)
      : { ...emptyBranch(), folders: [pathFolders[index + 1]], expanded: true };
  });
  return { root, branches };
}

function mergeFolders(existing: LibraryFolder[], additions: LibraryFolder[]): LibraryFolder[] {
  const replacements = new Map(additions.map((folder) => [folder.id, folder]));
  const merged = existing.map((folder) => replacements.get(folder.id) ?? folder);
  additions.forEach((folder) => {
    if (!existing.some((item) => item.id === folder.id)) merged.push(folder);
  });
  return merged;
}

function emptyBranch(): Branch {
  return { authoritative: false, folders: [], nextCursor: null, expanded: true, loading: false, error: false };
}

function isAbort(failure: unknown): boolean {
  return failure instanceof DOMException && failure.name === "AbortError";
}

function subscribeNarrowTree(onChange: () => void): () => void {
  if (typeof window === "undefined" || !window.matchMedia) return () => undefined;
  const query = window.matchMedia(narrowTreeQuery);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function isNarrowTree(): boolean {
  return typeof window !== "undefined" && Boolean(window.matchMedia?.(narrowTreeQuery).matches);
}
