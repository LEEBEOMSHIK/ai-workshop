"use client";

import Link from "next/link";
import { useCallback, useRef, useState, type FormEvent } from "react";

import { routes } from "../../shared/routing/routes";
import type { WorkspaceSummary } from "../workspaces/api";
import { JobStatus } from "../jobs/JobStatus";
import {
  browseLibrary,
  createFolder,
  type FolderSummary,
  getLibraryDocument,
  type DocumentSummary,
  type LibraryPage,
  uploadDocument,
  uploadDocumentVersion,
} from "./api";
import styles from "./DocumentLibrary.module.css";
import { LibraryTree } from "./LibraryTree";
import { LibraryViewer } from "./LibraryViewer";
import { UploadDialog } from "./UploadDialog";
import { type LibrarySelection, useLibraryPopState, writeLibrarySelection } from "./useLibraryNavigation";

interface DocumentBrowserProps {
  workspaceId: string;
  initialLibrary: LibraryPage;
  initialRoot: LibraryPage;
  initialWorkspaces: WorkspaceSummary[];
  initialDocument: DocumentSummary | null;
  initialVersionId: string | null;
  readOnly?: boolean;
  browse?: typeof browseLibrary;
  getDocument?: typeof getLibraryDocument;
  writeSelection?: typeof writeLibrarySelection;
  readSelection?: (search: string) => LibrarySelection;
  onRestoreWorkspace?: (workspaceId: string, selection: LibrarySelection) => void;
  onSelectWorkspace?: (workspaceId: string) => void;
  selectedDocumentIds?: ReadonlySet<string>;
  onToggleDocumentSelection?: (document: DocumentSummary, selected: boolean) => void;
  isDocumentSelectionDisabled?: (document: DocumentSummary) => boolean;
  backHref?: string | null;
  browserDescription?: string;
  navigationEnabled?: boolean;
  isFolderSelectionDisabled?: (folderId: string | null) => boolean;
}

const statusLabels: Record<DocumentSummary["status"], string> = {
  stored: "저장됨",
  processing: "처리 중",
  ready: "원본 준비됨",
  failed: "실패",
};

interface LibraryScope {
  folderId: string | null;
  generation: number;
}

export function DocumentBrowser({
  workspaceId,
  initialLibrary,
  initialRoot,
  initialWorkspaces,
  initialDocument,
  initialVersionId,
  readOnly = false,
  browse = browseLibrary,
  getDocument = getLibraryDocument,
  writeSelection: publishSelection = writeLibrarySelection,
  readSelection,
  onRestoreWorkspace,
  onSelectWorkspace,
  selectedDocumentIds,
  onToggleDocumentSelection,
  isDocumentSelectionDisabled,
  backHref = routes.workshopHome,
  browserDescription = "원본 파일과 버전을 로컬에서 관리합니다.",
  navigationEnabled = true,
  isFolderSelectionDisabled,
}: DocumentBrowserProps) {
  const [library, setLibrary] = useState(initialLibrary);
  const [selectedDocument, setSelectedDocument] = useState(initialDocument);
  const [selectedVersionId, setSelectedVersionId] = useState(initialVersionId);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [reconcileError, setReconcileError] = useState("");
  const [treeRoot, setTreeRoot] = useState(initialRoot);
  const [treeSelection, setTreeSelection] = useState(initialLibrary);
  const [treeRevision, setTreeRevision] = useState(0);
  const [selectionResolved, setSelectionResolved] = useState(true);
  const [loadingMoreDocuments, setLoadingMoreDocuments] = useState(false);
  const documentButtons = useRef(new Map<string, HTMLButtonElement>());
  const folderHeadingRef = useRef<HTMLHeadingElement | null>(null);
  const requestRef = useRef<{ controller: AbortController; sequence: number } | null>(null);
  const scopedControllers = useRef(new Set<AbortController>());
  const sequence = useRef(0);
  const scopeRef = useRef<LibraryScope>({ folderId: initialLibrary.folder?.id ?? null, generation: 0 });
  const retrySelectionRef = useRef<LibrarySelection>({
    folderId: initialLibrary.folder?.id ?? null,
    documentId: initialDocument?.id ?? null,
    versionId: initialVersionId,
  });
  const documentCursorRequests = useRef(new Set<string>());

  function beginScope(folderId: string | null): LibraryScope {
    requestRef.current?.controller.abort();
    scopedControllers.current.forEach((controller) => controller.abort());
    scopedControllers.current.clear();
    const scope = { folderId, generation: ++sequence.current };
    scopeRef.current = scope;
    return scope;
  }

  function updateScopeFolder(scope: LibraryScope, folderId: string | null): LibraryScope {
    if (scopeRef.current.generation !== scope.generation) return scope;
    const updated = { folderId, generation: scope.generation };
    scopeRef.current = updated;
    return updated;
  }

  function isCurrentScope(scope: LibraryScope): boolean {
    return scopeRef.current.generation === scope.generation && scopeRef.current.folderId === scope.folderId;
  }

  function publishTreePage(page: LibraryPage) {
    if (!page.folder) setTreeRoot(page);
    setTreeSelection(page);
    setTreeRevision((revision) => revision + 1);
  }

  const loadSelection = useCallback(async (selection: LibrarySelection, updateHistory = false) => {
    let scope = beginScope(selection.folderId);
    retrySelectionRef.current = selection;
    setSelectionResolved(false);
    setLoadingMoreDocuments(false);
    setCreatingFolder(false);
    setFolderName("");
    setError("");
    setReconcileError("");
    setSelectedDocument(null);
    setSelectedVersionId(null);
    if (selection.versionId && !selection.documentId) {
      setLibrary((page) => emptyLibrary(page));
      setLoading(false);
      setError("문서 없는 버전 주소는 열 수 없습니다.");
      return;
    }
    const controller = new AbortController();
    requestRef.current = { controller, sequence: scope.generation };
    setLoading(true);
    try {
      const exactDocument = selection.documentId
        ? await getDocument(workspaceId, selection.documentId, controller.signal)
        : null;
      if (exactDocument && selection.folderId && exactDocument.folder_id !== selection.folderId) {
        throw new Error("mismatched_selection");
      }
      const folderId = exactDocument?.folder_id ?? selection.folderId;
      scope = updateScopeFolder(scope, folderId);
      const page = await browse(workspaceId, { folderId, signal: controller.signal });
      if (controller.signal.aborted || !isCurrentScope(scope)) return;
      setLibrary(page);
      publishTreePage(page);
      setSelectionResolved(true);
      setSelectedDocument(exactDocument);
      setSelectedVersionId(exactDocument ? selection.versionId ?? exactDocument.active_version_id : null);
      if (updateHistory) publishSelection(workspaceId, {
        folderId,
        documentId: exactDocument?.id ?? null,
        versionId: exactDocument ? selection.versionId ?? exactDocument.active_version_id : null,
      });
    } catch (failure) {
      if (controller.signal.aborted || !isCurrentScope(scope)) return;
      setLibrary((page) => emptyLibrary(page));
      setError(failure instanceof Error && failure.message === "mismatched_selection"
        ? "폴더와 문서 선택이 일치하지 않습니다."
        : "선택한 위치를 불러오지 못했습니다. 권한과 주소를 확인해 주세요.");
    } finally {
      if (!controller.signal.aborted && isCurrentScope(scope)) setLoading(false);
    }
  }, [browse, getDocument, publishSelection, workspaceId]);

  useLibraryPopState(useCallback((selection: LibrarySelection) => {
    if (selection.workspaceId && selection.workspaceId !== workspaceId && onRestoreWorkspace) {
      onRestoreWorkspace(selection.workspaceId, selection);
      return;
    }
    void loadSelection(selection, false);
  }, [loadSelection, onRestoreWorkspace, workspaceId]), readSelection, navigationEnabled);

  function selectFolder(folderId: string | null) {
    if (isFolderSelectionDisabled?.(folderId)) return;
    void loadSelection({ folderId, documentId: null, versionId: null }, true);
  }

  function openDocument(document: DocumentSummary) {
    setSelectedDocument(document);
    setSelectedVersionId(document.active_version_id);
    publishSelection(workspaceId, { folderId: library.folder?.id ?? null, documentId: document.id, versionId: document.active_version_id });
  }

  function closeDocument() {
    const opener = selectedDocument ? documentButtons.current.get(selectedDocument.id) : null;
    setSelectedDocument(null);
    setSelectedVersionId(null);
    publishSelection(workspaceId, { folderId: library.folder?.id ?? null, documentId: null, versionId: null });
    (opener?.isConnected ? opener : folderHeadingRef.current)?.focus();
  }

  function captureScope(): LibraryScope {
    return { ...scopeRef.current };
  }

  async function reconcileScope(scope: LibraryScope, failureMessage: string, ensureFolder?: FolderSummary, ensureDocument?: DocumentSummary) {
    if (!isCurrentScope(scope)) return;
    const controller = new AbortController();
    scopedControllers.current.add(controller);
    setReconcileError("");
    try {
      const page = await browse(workspaceId, { folderId: scope.folderId, signal: controller.signal });
      if (controller.signal.aborted || !isCurrentScope(scope)) return;
      const withFolder = ensureFolder ? pageWithFolder(page, ensureFolder) : page;
      const reconciled = ensureDocument ? pageWithDocument(withFolder, ensureDocument) : withFolder;
      setLibrary(reconciled);
      publishTreePage(reconciled);
    } catch (failure) {
      if (!controller.signal.aborted && isCurrentScope(scope) && !isAbort(failure)) setReconcileError(failureMessage);
    } finally {
      scopedControllers.current.delete(controller);
    }
  }

  async function handleUpload(file: File) {
    const scope = captureScope();
    const uploaded = await uploadDocument(workspaceId, file, scope.folderId);
    await reconcileScope(scope, "문서는 저장됐지만 목록을 새로 맞추지 못했습니다.", undefined, uploaded);
  }

  async function handleVersionUpload(documentId: string, file: File) {
    const scope = captureScope();
    const updated = await uploadDocumentVersion(documentId, file);
    if (!isCurrentScope(scope)) return;
    setLibrary((current) => ({ ...current, documents: current.documents.map((document) => document.id === updated.id ? updated : document) }));
    setSelectedDocument((current) => current?.id === updated.id ? updated : current);
  }

  async function submitFolder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = folderName.trim();
    if (!name) { setError("폴더 이름을 입력해 주세요."); return; }
    const scope = captureScope();
    let created: FolderSummary;
    try {
      created = await createFolder(workspaceId, name, scope.folderId);
    } catch {
      if (isCurrentScope(scope)) setError("폴더를 만들지 못했습니다. 이름과 권한을 확인해 주세요.");
      return;
    }
    if (!isCurrentScope(scope)) return;
    setError("");
    setFolderName("");
    setCreatingFolder(false);
    setLibrary((page) => pageWithFolder(page, created));
    setTreeSelection((page) => pageWithFolder(page, created));
    if (scope.folderId === null) setTreeRoot((page) => pageWithFolder(page, created));
    setTreeRevision((revision) => revision + 1);
    await reconcileScope(scope, "폴더는 만들어졌지만 목록을 새로 맞추지 못했습니다.", created);
  }

  async function loadMoreDocuments() {
    const cursor = library.next_document_cursor;
    if (!cursor) return;
    const scope = captureScope();
    const requestKey = `${scope.generation}:${scope.folderId ?? "root"}:${cursor}`;
    if (documentCursorRequests.current.has(requestKey)) return;
    documentCursorRequests.current.add(requestKey);
    setLoadingMoreDocuments(true);
    const controller = new AbortController();
    scopedControllers.current.add(controller);
    try {
      const page = await browse(workspaceId, { folderId: scope.folderId, documentCursor: cursor, signal: controller.signal });
      if (controller.signal.aborted || !isCurrentScope(scope)) return;
      setLibrary((current) => isPageInScope(current, scope) && current.next_document_cursor === cursor
        ? { ...current, documents: mergeDocuments(current.documents, page.documents), next_document_cursor: page.next_document_cursor }
        : current);
    } catch (failure) {
      if (!controller.signal.aborted && isCurrentScope(scope) && !isAbort(failure)) setError("다음 문서 목록을 불러오지 못했습니다.");
    } finally {
      scopedControllers.current.delete(controller);
      documentCursorRequests.current.delete(requestKey);
      if (isCurrentScope(scope)) setLoadingMoreDocuments(false);
    }
  }

  return <main className={styles.shell}>
    <header className={styles.header}>
      <div>
        <p className={styles.kicker}>FILE CABINET</p>
        <h1>{library.workspace.name}</h1>
        <p>{workspaceKindLabel(library.workspace.kind)} · {browserDescription}</p>
      </div>
      {backHref ? <Link className={styles.backLink} href={backHref}>파일함으로</Link> : null}
    </header>
    <div className={`${styles.explorer} ${selectedDocument ? styles.explorerWithViewer : ""}`}>
      <LibraryTree key={`${workspaceId}:${treeRevision}`} workspaces={initialWorkspaces} currentWorkspaceId={workspaceId} selectedFolderId={library.folder?.id ?? null} initialRoot={treeRoot} initialSelection={treeSelection} onSelectFolder={selectFolder} browse={browse} onSelectWorkspace={onSelectWorkspace} isFolderSelectionDisabled={isFolderSelectionDisabled} />
      <section className={styles.browser} aria-label="현재 폴더 문서">
        {selectionResolved ? <nav className={styles.breadcrumbs} aria-label="현재 폴더 경로">
          <button type="button" disabled={isFolderSelectionDisabled?.(null) ?? false} onClick={() => selectFolder(null)}>{library.workspace.name}</button>
          {library.ancestors.map((folder) => <span key={folder.id}>/ <button type="button" disabled={isFolderSelectionDisabled?.(folder.id) ?? false} onClick={() => selectFolder(folder.id)}>{folder.name}</button></span>)}
          {library.folder ? <span aria-current="page">/ {library.folder.name}</span> : <span aria-current="page">/ 미분류</span>}
        </nav> : <p className={styles.breadcrumbs}>선택한 폴더를 확인하고 있습니다.</p>}
        <div className={styles.toolbar}>
          <h2 ref={folderHeadingRef} tabIndex={-1}>{selectionResolved ? library.folder?.name ?? "미분류 문서" : "폴더 선택 확인 중"}</h2>
          {!readOnly ? <div className={styles.toolbarActions}>
            <button type="button" disabled={!selectionResolved} aria-expanded={creatingFolder} onClick={() => setCreatingFolder((current) => !current)}>새 폴더</button>
            <UploadDialog disabled={!selectionResolved} onUpload={handleUpload} />
          </div> : null}
        </div>
        {!readOnly && selectionResolved && creatingFolder ? <form className={styles.folderForm} aria-label="새 폴더 만들기" onSubmit={submitFolder}>
          <label>폴더 이름 <input value={folderName} maxLength={180} onChange={(event) => setFolderName(event.target.value)} /></label>
          <button type="submit">폴더 만들기</button>
        </form> : null}
        {loading ? <p role="status">폴더를 불러오는 중…</p> : null}
        {error ? <div className={styles.error} role="alert"><p>{error}</p><button type="button" onClick={() => loadSelection(retrySelectionRef.current, false)}>다시 시도</button></div> : null}
        {reconcileError ? <div className={styles.error} role="alert"><p>{reconcileError}</p><button type="button" onClick={() => reconcileScope(captureScope(), reconcileError)}>목록 다시 맞추기</button></div> : null}
        {!loading && !error && library.documents.length === 0 ? <p className={styles.empty}>이 폴더에는 문서가 없습니다.</p> : null}
        <div className={styles.list}>
          {selectionResolved ? library.documents.map((document) => <article className={styles.fileRow} key={document.id}>
            <div className={styles.fileIdentity}>
            <button ref={(node) => {
              if (node) documentButtons.current.set(document.id, node);
              else documentButtons.current.delete(document.id);
            }} className={styles.fileOpen} type="button" aria-label={`${document.name} 열기`} onClick={() => openDocument(document)}>{document.name}</button>
            <div className={styles.fileMeta}>
              <span>최신 버전 {document.latest_version}</span>
              {document.active_version_id && document.active_version_id !== document.latest_version_id ? <span> · 이전 활성 원본 열람 가능</span> : null}
            </div>
            </div>
            <span className={`${styles.state} ${document.status === "ready" ? styles.ready : ""}`}>{statusLabels[document.status]}</span>
            {onToggleDocumentSelection ? <label className={styles.documentSelection}><input type="checkbox" aria-label={`${document.name} 선택`} checked={selectedDocumentIds?.has(document.id) ?? false} disabled={isDocumentSelectionDisabled?.(document) ?? false} onChange={(event) => onToggleDocumentSelection(document, event.target.checked)} /> 선택</label> : null}
            {!readOnly ? <UploadDialog buttonLabel="새 버전 올리기" inputLabel={`${document.name} 새 버전 파일`} onUpload={(file) => handleVersionUpload(document.id, file)} /> : null}
            {document.job_id ? <div className={styles.fileJob}><JobStatus jobId={document.job_id} initialStatus="queued" /></div> : null}
          </article>) : null}
        </div>
        {selectionResolved && library.next_document_cursor ? <button type="button" disabled={loadingMoreDocuments} onClick={loadMoreDocuments}>문서 더 보기</button> : null}
      </section>
      {selectedDocument ? <LibraryViewer key={`${selectedDocument.id}:${selectedVersionId ?? "active"}`} document={selectedDocument} initialVersionId={selectedVersionId} onClose={closeDocument} onVersionChange={(versionId) => {
        setSelectedVersionId(versionId);
        publishSelection(workspaceId, { folderId: library.folder?.id ?? null, documentId: selectedDocument.id, versionId });
      }} /> : null}
    </div>
  </main>;
}

function workspaceKindLabel(kind: WorkspaceSummary["kind"]): string {
  return { company: "회사 공간", team: "팀 공간", personal: "개인 공간", temporary: "임시 공간" }[kind];
}

function emptyLibrary(page: LibraryPage): LibraryPage {
  return { ...page, ancestors: [], folder: null, folders: [], documents: [], next_document_cursor: null, next_folder_cursor: null };
}

function pageWithFolder(page: LibraryPage, folder: FolderSummary): LibraryPage {
  if ((page.folder?.id ?? null) !== folder.parent_id || page.folders.some((item) => item.id === folder.id)) return page;
  return { ...page, folders: [...page.folders, { ...folder, has_children: false }] };
}

function pageWithDocument(page: LibraryPage, uploaded: DocumentSummary): LibraryPage {
  const existing = page.documents.find((document) => document.id === uploaded.id);
  if (!existing) return { ...page, documents: [uploaded, ...page.documents] };
  return {
    ...page,
    documents: page.documents.map((document) => document.id === uploaded.id
      ? { ...document, job_id: document.job_id ?? uploaded.job_id }
      : document),
  };
}

function mergeDocuments(existing: DocumentSummary[], additions: DocumentSummary[]): DocumentSummary[] {
  const ids = new Set(existing.map((document) => document.id));
  return [...existing, ...additions.filter((document) => !ids.has(document.id))];
}

function isPageInScope(page: LibraryPage, scope: LibraryScope): boolean {
  return (page.folder?.id ?? null) === scope.folderId;
}

function isAbort(failure: unknown): boolean {
  return failure instanceof DOMException && failure.name === "AbortError";
}
