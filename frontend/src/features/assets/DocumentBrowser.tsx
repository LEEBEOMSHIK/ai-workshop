"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { routes } from "../../shared/routing/routes";
import { getWorkspaceCapabilities, type WorkspaceSummary } from "../workspaces/api";
import { ApiError } from "../../shared/api/client";
import { WorkspaceMemberPermissions } from "../workspaces/WorkspaceMemberPermissions";
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
  moveDocument,
  moveFolder,
} from "./api";
import styles from "./DocumentLibrary.module.css";
import { LibraryTree } from "./LibraryTree";
import { LibraryViewer } from "./LibraryViewer";
import { UploadDialog } from "./UploadDialog";
import { MoveDialog, MoveOutcomeUnknown, isUnknownMoveFailure } from "./MoveDialog";
import { documentMoveSource, folderMoveSource, type MoveResult, type MoveSource } from "./movement";
import { useAssetMovement } from "./useAssetMovement";
import { type LibrarySelection, useLibraryPopState, writeLibrarySelection } from "./useLibraryNavigation";

interface DocumentBrowserProps {
  workspaceId: string;
  initialLibrary: LibraryPage;
  initialRoot: LibraryPage;
  initialWorkspaces: WorkspaceSummary[];
  initialDocument: DocumentSummary | null;
  initialVersionId: string | null;
  readOnly?: boolean;
  showMemberManagement?: boolean;
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
  beforeMutation?: (folderId: string | null, documentId: string | undefined, signal: AbortSignal) => Promise<void>;
  beforeMove?: (source: MoveSource, destinationId: string | null, signal: AbortSignal) => Promise<void>;
  onMoveCommitted?: (source: MoveSource, result: MoveResult) => Promise<void> | void;
  onMoveUncertain?: (source: MoveSource) => void;
  onMoveRejected?: (source: MoveSource) => void;
  onMoveScopeInvalidated?: () => void;
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

export function DocumentBrowser(props: DocumentBrowserProps) {
  return <DocumentBrowserScope key={props.workspaceId} {...props} />;
}

function DocumentBrowserScope({
  workspaceId,
  initialLibrary,
  initialRoot,
  initialWorkspaces,
  initialDocument,
  initialVersionId,
  readOnly = false,
  showMemberManagement = false,
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
  beforeMutation,
  beforeMove,
  onMoveCommitted,
  onMoveUncertain,
  onMoveRejected,
  onMoveScopeInvalidated,
}: DocumentBrowserProps) {
  const [rights, setRights] = useState<"loading" | "write" | "read" | "failed" | "revoked">("loading");
  const [rightsRevision, setRightsRevision] = useState(0);
  const [uploadRevision, setUploadRevision] = useState(0);
  const [mutating, setMutating] = useState(false);
  const [mutationMessage, setMutationMessage] = useState("");
  const [folderError, setFolderError] = useState("");
  const mutationLock = useRef(false);
  const capabilityController = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const writable = !readOnly && rights === "write";
  const writableRef = useRef(writable);
  useEffect(() => { writableRef.current = writable; }, [writable]);
  useEffect(() => {
    const controller = new AbortController();
    capabilityController.current = controller;
    void getWorkspaceCapabilities(workspaceId, controller.signal).then((capabilities) => {
      if (!controller.signal.aborted) setRights(capabilities.read === true && capabilities.write === true ? "write" : "read");
    }).catch(() => { if (!controller.signal.aborted) setRights("failed"); });
    return () => controller.abort();
  }, [workspaceId, rightsRevision]);
  const [library, setLibrary] = useState(initialLibrary);
  const [selectedDocument, setSelectedDocument] = useState(initialDocument);
  const [selectedVersionId, setSelectedVersionId] = useState(initialVersionId);
  const viewerIdentityGeneration = useRef(0);
  const latestViewerVersion = useRef(initialVersionId);
  const selectViewerVersion = useCallback((versionId: string | null) => {
    latestViewerVersion.current = versionId;
    setSelectedVersionId(versionId);
  }, []);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [folderName, setFolderName] = useState("");
  const [reconcileError, setReconcileError] = useState("");
  const [moveRecovery, setMoveRecovery] = useState<{ source: MoveSource; result: MoveResult | null } | null>(null);
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
  const folderInputRef = useRef<HTMLInputElement>(null);
  const folderButtonRef = useRef<HTMLButtonElement>(null);
  const movement = useAssetMovement(writable && selectionResolved && !mutating && !loading && !moveRecovery);
  const clearMovementRef = useRef(movement.clear);
  useEffect(() => { clearMovementRef.current = movement.clear; }, [movement.clear]);
  const moveScopeInvalidatedRef = useRef(onMoveScopeInvalidated);
  useEffect(() => { moveScopeInvalidatedRef.current = onMoveScopeInvalidated; }, [onMoveScopeInvalidated]);

  useEffect(() => {
    mounted.current = true;
    const controllers = scopedControllers.current;
    return () => { mounted.current = false; requestRef.current?.controller.abort(); controllers.forEach((request) => request.abort()); };
  }, []);
  useEffect(() => { if (creatingFolder) folderInputRef.current?.focus(); }, [creatingFolder]);

  function cancelFolder() {
    setCreatingFolder(false);
    setFolderName("");
    setFolderError("");
    folderButtonRef.current?.focus();
  }

  function beginScope(folderId: string | null): LibraryScope {
    // Retire the initiating selection before cancelling transport, including same-workspace history.
    moveScopeInvalidatedRef.current?.();
    viewerIdentityGeneration.current += 1;
    clearMovementRef.current();
    setMoveRecovery(null);
    requestRef.current?.controller.abort();
    scopedControllers.current.forEach((controller) => controller.abort());
    scopedControllers.current.clear();
    const scope = { folderId, generation: ++sequence.current };
    scopeRef.current = scope;
    setUploadRevision((revision) => revision + 1);
    return scope;
  }

  function updateScopeFolder(scope: LibraryScope, folderId: string | null): LibraryScope {
    if (scopeRef.current.generation !== scope.generation) return scope;
    const updated = { folderId, generation: scope.generation };
    scopeRef.current = updated;
    return updated;
  }

  function isCurrentScope(scope: LibraryScope): boolean {
    return mounted.current && scopeRef.current.generation === scope.generation && scopeRef.current.folderId === scope.folderId;
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
    setFolderError("");
    setMutationMessage("");
    setError("");
    setReconcileError("");
    setSelectedDocument(null);
    selectViewerVersion(null);
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
      selectViewerVersion(exactDocument ? selection.versionId ?? exactDocument.active_version_id : null);
      if (updateHistory) publishSelection(workspaceId, {
        folderId,
        documentId: exactDocument?.id ?? null,
        versionId: exactDocument ? selection.versionId ?? exactDocument.active_version_id : null,
      });
    } catch (failure) {
      if (controller.signal.aborted || !isCurrentScope(scope)) return;
      revokeOnFailure(failure);
      setLibrary((page) => emptyLibrary(page));
      setError(failure instanceof Error && failure.message === "mismatched_selection"
        ? "폴더와 문서 선택이 일치하지 않습니다."
        : "선택한 위치를 불러오지 못했습니다. 권한과 주소를 확인해 주세요.");
    } finally {
      if (!controller.signal.aborted && isCurrentScope(scope)) setLoading(false);
    }
  }, [browse, getDocument, publishSelection, selectViewerVersion, workspaceId]);

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
    if (moveRecovery) return;
    viewerIdentityGeneration.current += 1;
    setSelectedDocument(document);
    selectViewerVersion(document.active_version_id);
    publishSelection(workspaceId, { folderId: library.folder?.id ?? null, documentId: document.id, versionId: document.active_version_id });
  }

  function closeDocument() {
    viewerIdentityGeneration.current += 1;
    const opener = selectedDocument ? documentButtons.current.get(selectedDocument.id) : null;
    setSelectedDocument(null);
    selectViewerVersion(null);
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
      if (!controller.signal.aborted && isCurrentScope(scope) && !isAbort(failure)) {
        revokeOnFailure(failure);
        setReconcileError(failureMessage);
      }
    } finally {
      scopedControllers.current.delete(controller);
    }
  }

  async function handleUpload(file: File) {
    const scope = captureScope();
    await mutate(scope, async () => {
      const uploaded = await uploadDocument(workspaceId, file, scope.folderId);
      await reconcileScope(scope, "문서는 저장됐지만 목록을 새로 맞추지 못했습니다.", undefined, uploaded);
    });
  }

  async function handleVersionUpload(documentId: string, file: File) {
    const scope = captureScope();
    await mutate(scope, async () => {
    const updated = await uploadDocumentVersion(documentId, file);
    if (!isCurrentScope(scope)) return;
    setLibrary((current) => ({ ...current, documents: current.documents.map((document) => document.id === updated.id ? updated : document) }));
    setSelectedDocument((current) => current?.id === updated.id ? updated : current);
    }, documentId);
  }

  async function mutate(scope: LibraryScope, action: () => Promise<void>, documentId?: string) {
    if (!writableRef.current || mutationLock.current || !selectionResolved || isFolderSelectionDisabled?.(scope.folderId)) throw new Error("write_unavailable");
    mutationLock.current = true;
    const controller = new AbortController();
    scopedControllers.current.add(controller);
    setMutating(true);
    setMutationMessage("");
    try {
      if (beforeMutation) await beforeMutation(scope.folderId, documentId, controller.signal);
      if (!isCurrentScope(scope) || !writableRef.current) throw new Error("write_unavailable");
      await action();
    } catch (failure) {
      if (isCurrentScope(scope)) revokeOnFailure(failure);
      throw failure;
    } finally {
      scopedControllers.current.delete(controller);
      mutationLock.current = false;
      if (mounted.current) setMutating(false);
    }
  }

  function revokeOnFailure(failure: unknown) {
    if (failure instanceof ApiError && [401, 403, 404].includes(failure.status)) {
      capabilityController.current?.abort();
      writableRef.current = false;
      setRights("revoked");
      setUploadRevision((revision) => revision + 1);
    }
  }

  async function submitFolder(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const name = folderName.trim();
    if (mutationLock.current) return;
    if (!name) { setFolderError("폴더 이름을 입력해 주세요."); return; }
    const scope = captureScope();
    try {
      await mutate(scope, async () => {
        const created = await createFolder(workspaceId, name, scope.folderId);
        if (!isCurrentScope(scope)) return;
        setFolderError("");
        setMutationMessage("폴더를 만들었습니다.");
        setFolderName("");
        setCreatingFolder(false);
        setLibrary((page) => pageWithFolder(page, created));
        setTreeSelection((page) => pageWithFolder(page, created));
        if (scope.folderId === null) setTreeRoot((page) => pageWithFolder(page, created));
        setTreeRevision((revision) => revision + 1);
        await reconcileScope(scope, "폴더는 만들어졌지만 목록을 새로 맞추지 못했습니다.", created);
      });
    } catch {
      if (isCurrentScope(scope)) setFolderError("폴더를 만들지 못했습니다. 이름과 권한을 확인한 뒤 다시 만들어 주세요.");
      return;
    }
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
      if (!controller.signal.aborted && isCurrentScope(scope) && !isAbort(failure)) { revokeOnFailure(failure); setError("다음 문서 목록을 불러오지 못했습니다."); }
    } finally {
      scopedControllers.current.delete(controller);
      documentCursorRequests.current.delete(requestKey);
      if (isCurrentScope(scope)) setLoadingMoreDocuments(false);
    }
  }

  async function reconcileMove(source: MoveSource, result: MoveResult | null, signal: AbortSignal) {
    const scope = captureScope();
    const currentDocument = selectedDocument;
    const currentViewerGeneration = viewerIdentityGeneration.current;
    // A committed move changes ancestor caches even if the currently open folder keeps its ID.
    const destinationId = result ? "folder_id" in result ? result.folder_id : result.parent_id : source.parentId;
    const folderIds = [...new Set([null, scope.folderId, source.parentId, destinationId])];
    const pages = await Promise.all(folderIds.map((folderId) => browse(workspaceId, { folderId, signal })));
    const exact = currentDocument ? await getDocument(workspaceId, currentDocument.id, signal) : null;
    if (signal.aborted || !isCurrentScope(scope)) return;
    const current = pages.find((page) => (page.folder?.id ?? null) === scope.folderId);
    const root = pages.find((page) => page.folder === null);
    if (!current || !root) throw new Error("movement_refresh_incomplete");
    setLibrary(current); setTreeRoot(root); setTreeSelection(current); setTreeRevision((revision) => revision + 1);
    const viewerUnchanged = viewerIdentityGeneration.current === currentViewerGeneration;
    if (viewerUnchanged) setSelectedDocument((selected) => selected?.id === currentDocument?.id ? exact : selected);
    if (viewerUnchanged && exact && currentDocument?.id === exact.id) {
      // Keep the open document address restorable even when the list stays at its source folder.
      const selection = { folderId: exact.folder_id, documentId: exact.id, versionId: latestViewerVersion.current ?? exact.active_version_id };
      retrySelectionRef.current = selection;
      publishSelection(workspaceId, selection);
    }
    setMutationMessage(result ? "이동을 완료했습니다." : "현재 위치를 새로 확인했습니다. 다시 이동하려면 항목을 선택해 주세요.");
    setMoveRecovery(null);
  }

  async function refreshMoveRecovery() {
    if (!moveRecovery || mutationLock.current) return;
    const scope = captureScope(); const controller = new AbortController();
    mutationLock.current = true; scopedControllers.current.add(controller); setMutating(true);
    try { await reconcileMove(moveRecovery.source, moveRecovery.result, controller.signal); }
    catch (failure) { if (!controller.signal.aborted && isCurrentScope(scope)) revokeOnFailure(failure); }
    finally { scopedControllers.current.delete(controller); mutationLock.current = false; if (mounted.current) setMutating(false); }
  }

  async function executeMove(source: MoveSource, destination: LibraryPage, signal: AbortSignal, committed: (result: MoveResult) => void) {
    const scope = captureScope();
    if (!writableRef.current || mutationLock.current || !selectionResolved || signal.aborted) throw new Error("write_unavailable");
    mutationLock.current = true; setMutating(true);
    try {
      if (beforeMove) await beforeMove(source, destination.folder?.id ?? null, signal);
      if (signal.aborted || !isCurrentScope(scope) || !writableRef.current) {
        if (!signal.aborted && isCurrentScope(scope)) onMoveRejected?.(source);
        throw new Error("write_unavailable");
      }
      let result: MoveResult;
      try {
        const body = { destination_folder_id: destination.folder?.id ?? null, expected_revision: source.revision };
        result = source.kind === "document" ? await moveDocument(workspaceId, source.id, body, signal) : await moveFolder(workspaceId, source.id, body, signal);
      } catch (failure) {
        if (isUnknownMoveFailure(failure)) {
          if (isCurrentScope(scope)) setMoveRecovery({ source, result: null });
          if (!signal.aborted && isCurrentScope(scope)) onMoveUncertain?.(source);
          throw new MoveOutcomeUnknown();
        }
        if (!signal.aborted && isCurrentScope(scope)) onMoveRejected?.(source);
        throw failure;
      }
      committed(result);
      if (isCurrentScope(scope)) {
        setMoveRecovery({ source, result });
        scopedControllers.current.forEach((controller) => controller.abort());
        setLoadingMoreDocuments(false);
      }
      // Selection validation belongs to the domain and must precede applying a refreshed view.
      await onMoveCommitted?.(source, result);
      if (signal.aborted || !isCurrentScope(scope)) return;
      await reconcileMove(source, result, signal);
    } finally { mutationLock.current = false; if (mounted.current) setMutating(false); }
  }

  return <main className={styles.shell} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "none"; }} onDrop={(event) => event.preventDefault()}>
    <header className={styles.header}>
      <div>
        <p className={styles.kicker}>FILE CABINET</p>
        <h1>{library.workspace.name}</h1>
        <p>{workspaceKindLabel(library.workspace.kind)} · {browserDescription}</p>
      </div>
      {backHref ? <Link className={styles.backLink} href={backHref}>파일함으로</Link> : null}
    </header>
    {showMemberManagement ? <WorkspaceMemberPermissions key={workspaceId} workspaceId={workspaceId} /> : null}
    <div className={`${styles.explorer} ${selectedDocument ? styles.explorerWithViewer : ""}`}>
      <LibraryTree key={`${workspaceId}:${treeRevision}`} workspaces={initialWorkspaces} currentWorkspaceId={workspaceId} selectedFolderId={library.folder?.id ?? null} initialRoot={treeRoot} initialSelection={treeSelection} onSelectFolder={selectFolder} browse={browse} onSelectWorkspace={onSelectWorkspace} isFolderSelectionDisabled={isFolderSelectionDisabled}
        movement={!readOnly ? { enabled: writable && selectionResolved && !mutating && !loading && !movement.pending && !moveRecovery, open: (folder, opener) => movement.open(folderMoveSource(folder, workspaceId), folder.parent_id, opener), sourceBindings: (folder) => movement.sourceBindings(folderMoveSource(folder, workspaceId)), destinationBindings: movement.destinationBindings } : undefined} />
      <section className={styles.browser} aria-label="현재 폴더 문서">
        {selectionResolved ? <nav className={styles.breadcrumbs} aria-label="현재 폴더 경로">
          <button type="button" disabled={isFolderSelectionDisabled?.(null) ?? false} onClick={() => selectFolder(null)}>{library.workspace.name}</button>
          {library.ancestors.map((folder) => <span key={folder.id}>/ <button type="button" disabled={isFolderSelectionDisabled?.(folder.id) ?? false} onClick={() => selectFolder(folder.id)}>{folder.name}</button></span>)}
          {library.folder ? <span aria-current="page">/ {library.folder.name}</span> : <span aria-current="page">/ root</span>}
        </nav> : <p className={styles.breadcrumbs}>선택한 폴더를 확인하고 있습니다.</p>}
        <div className={styles.toolbar}>
          <h2 ref={folderHeadingRef} tabIndex={-1}>{selectionResolved ? library.folder?.name ?? "root" : "폴더 선택 확인 중"}</h2>
          {!readOnly ? <div className={styles.toolbarActions}>
            <button ref={folderButtonRef} type="button" disabled={!selectionResolved || !writable || mutating || isFolderSelectionDisabled?.(library.folder?.id ?? null)} aria-expanded={creatingFolder} onClick={() => creatingFolder ? cancelFolder() : setCreatingFolder(true)}>새 폴더</button>
            <UploadDialog key={uploadRevision} disabled={!selectionResolved || !writable || mutating || isFolderSelectionDisabled?.(library.folder?.id ?? null)} onUpload={handleUpload} />
          </div> : null}
        </div>
        {selectionResolved ? <p className={styles.managementHint}>저장 위치: {workspaceKindLabel(library.workspace.kind)} / {library.workspace.name} / {[...library.ancestors.map((folder) => folder.name), library.folder?.name ?? "root"].join(" / ")}</p> : null}
        {readOnly ? <p>읽기 전용 · 현재 위치에서는 파일을 변경할 수 없습니다.</p> : rights === "loading" ? <p role="status">파일 관리 권한을 확인하는 중…</p> : rights !== "write" ? <p>읽기 전용 · {rights === "failed" ? "권한을 확인하지 못했습니다." : rights === "revoked" ? "권한이 변경되었습니다." : "업로드와 폴더 생성에는 쓰기 권한이 필요합니다."} <button type="button" onClick={() => { setRights("loading"); setRightsRevision((revision) => revision + 1); }}>권한 다시 확인</button></p> : null}
        {mutating ? <p role="status">파일 변경을 저장하는 중…</p> : null}
        {mutationMessage ? <p role="status">{mutationMessage}</p> : null}
        {moveRecovery && !movement.pending ? <div className={styles.error} role="alert"><p>{moveRecovery.result ? "이동 완료, 목록 새로고침 필요" : "이동 결과를 확인하지 못했습니다. 목록을 새로고침해 현재 위치를 확인해 주세요."}</p><p>현재 위치를 확인할 때까지 목록의 문서 열기와 선택을 잠시 사용할 수 없습니다.</p><button type="button" disabled={mutating} onClick={refreshMoveRecovery}>목록 새로고침</button></div> : null}
        {!readOnly && selectionResolved && creatingFolder ? <form className={styles.folderForm} aria-label="새 폴더 만들기" onSubmit={submitFolder}>
          <label>폴더 이름 <input ref={folderInputRef} value={folderName} disabled={mutating || !writable} maxLength={180} onChange={(event) => setFolderName(event.target.value)} /></label>
          <button type="submit" disabled={!writable || mutating}>폴더 만들기</button>
          <button type="button" disabled={mutating} onClick={cancelFolder}>폴더 만들기 취소</button>
          {folderError ? <p role="alert">{folderError}</p> : null}
        </form> : null}
        {loading ? <p role="status">폴더를 불러오는 중…</p> : null}
        {error ? <div className={styles.error} role="alert"><p>{error}</p><button type="button" onClick={() => loadSelection(retrySelectionRef.current, false)}>다시 시도</button></div> : null}
        {reconcileError ? <div className={styles.error} role="alert"><p>{reconcileError}</p><button type="button" onClick={() => reconcileScope(captureScope(), reconcileError)}>목록 다시 맞추기</button></div> : null}
        {!loading && !error && library.documents.length === 0 ? <p className={styles.empty}>이 폴더에는 문서가 없습니다.</p> : null}
        <div className={styles.list}>
          {selectionResolved ? library.documents.map((document) => <article className={styles.fileRow} key={document.id} {...movement.sourceBindings(documentMoveSource(document))}>
            <div className={styles.fileIdentity}>
            <button ref={(node) => {
              if (node) documentButtons.current.set(document.id, node);
              else documentButtons.current.delete(document.id);
            }} className={styles.fileOpen} type="button" aria-label={`${document.name} 열기`} disabled={!!moveRecovery} onClick={() => openDocument(document)}>{document.name}</button>
            <div className={styles.fileMeta}>
              <span>최신 버전 {document.latest_version}</span>
              {document.active_version_id && document.active_version_id !== document.latest_version_id ? <span> · 이전 활성 원본 열람 가능</span> : null}
            </div>
            </div>
            <span className={`${styles.state} ${document.status === "ready" ? styles.ready : ""}`}>{statusLabels[document.status]}</span>
            {onToggleDocumentSelection ? <label className={styles.documentSelection}><input type="checkbox" aria-label={`${document.name} 선택`} checked={selectedDocumentIds?.has(document.id) ?? false} disabled={!!moveRecovery || (isDocumentSelectionDisabled?.(document) ?? false)} onChange={(event) => { if (!moveRecovery) onToggleDocumentSelection(document, event.target.checked); }} /> 선택</label> : null}
            {!readOnly ? <div className={styles.fileActions}>
              <button className={styles.moveButton} type="button" aria-label={`${document.name} 이동`} disabled={!writable || mutating || !!movement.pending || !!moveRecovery || !documentMoveSource(document)} onClick={(event) => movement.open(documentMoveSource(document), document.folder_id, event.currentTarget)}>이동</button>
              <UploadDialog key={`${uploadRevision}:${document.id}`} disabled={!writable || mutating || isFolderSelectionDisabled?.(library.folder?.id ?? null)} buttonLabel="새 버전 올리기" inputLabel={`${document.name} 새 버전 파일`} onUpload={(file) => handleVersionUpload(document.id, file)} />
            </div> : null}
            {document.job_id ? <div className={styles.fileJob}><JobStatus jobId={document.job_id} initialStatus="queued" /></div> : null}
          </article>) : null}
        </div>
        {selectionResolved && library.next_document_cursor ? <button type="button" disabled={loadingMoreDocuments} onClick={loadMoreDocuments}>문서 더 보기</button> : null}
      </section>
      {selectedDocument ? <LibraryViewer key={`${selectedDocument.id}:${selectedVersionId ?? "active"}`} document={selectedDocument} initialVersionId={selectedVersionId} keyboardEnabled={!movement.pending} onClose={closeDocument} onVersionChange={(versionId) => {
        selectViewerVersion(versionId);
        publishSelection(workspaceId, { folderId: selectedDocument.folder_id, documentId: selectedDocument.id, versionId });
      }} /> : null}
    </div>
    {movement.pending ? <MoveDialog pending={movement.pending} writable={writable} browse={browse} getDocument={getDocument} execute={executeMove} reconcile={reconcileMove} onFailure={revokeOnFailure} onClose={movement.clear} fallbackFocus={() => folderHeadingRef.current} /> : null}
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
