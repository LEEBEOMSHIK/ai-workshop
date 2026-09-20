"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { DocumentBrowser } from "../../assets/DocumentBrowser";
import type { DocumentSummary, LibraryPage } from "../../assets/api";
import { assertMoveSourceUnchanged, documentMoveSource, folderMoveSource, type MoveSource } from "../../assets/movement";
import { readLibrarySelection, type LibrarySelection, writeLibrarySelection } from "../../assets/useLibraryNavigation";
import { ApiError } from "../../../shared/api/client";
import { ragDomainChatPath, ragDomainFilesPath } from "../../../shared/routing/routes";
import { DomainNavigation } from "./DomainNavigation";
import { browseDomainLibrary, getDomainLibraryDocument, type DomainLibraryContext } from "./library-api";
import styles from "./DomainFileCabinet.module.css";

const INVALIDATION_MESSAGE = "파일함 권한 또는 도메인 연결이 변경되었습니다. 도메인을 다시 선택해 주세요.";

interface CabinetView {
  revision: number;
  workspaceId: string;
  library: LibraryPage;
  root: LibraryPage;
  document: DocumentSummary | null;
  versionId: string | null;
}

export interface DomainFileCabinetProps {
  slug: string;
  context: DomainLibraryContext;
  initialLibrary: LibraryPage;
  initialRoot: LibraryPage;
  initialDocument: DocumentSummary | null;
  initialVersionId: string | null;
  initialSelectedDocuments?: DocumentSummary[];
  actionLabel?: string;
  onApplySelection?: (documents: DocumentSummary[]) => void;
  allowEmptySelection?: boolean;
  embedded?: boolean;
  allowedFolderIdsByWorkspace?: Readonly<Record<string, readonly string[]>>;
  onSelectionInvalidated?: () => void;
}

export function DomainFileCabinet({
  slug,
  context,
  initialLibrary,
  initialRoot,
  initialDocument,
  initialVersionId,
  initialSelectedDocuments = [],
  actionLabel = "선택 문서로 대화",
  onApplySelection,
  allowEmptySelection = false,
  embedded = false,
  allowedFolderIdsByWorkspace,
  onSelectionInvalidated,
}: DomainFileCabinetProps) {
  const router = useRouter();
  const [view, setView] = useState<CabinetView>({ revision: 0, workspaceId: initialLibrary.workspace.id, library: initialLibrary, root: initialRoot, document: initialDocument, versionId: initialVersionId });
  const [selected, setSelected] = useState(() => new Map(initialSelectedDocuments.map((document) => [document.id, document])));
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState("");
  const [invalidated, setInvalidated] = useState(false);
  const [revalidating, setRevalidating] = useState(false);
  const selectedRef = useRef(selected);
  const validationRequest = useRef<AbortController | null>(null);
  const selectionGeneration = useRef(0);
  const invalidationNotified = useRef(false);
  const mounted = useRef(true);
  const moveObligation = useRef<{ source: MoveSource; generation: number; selectedIds: Set<string> } | null>(null);
  const workspaceRequest = useRef<AbortController | null>(null);
  const selectionIdentity = `${slug}:${context.domain_id}:${context.connection_version_id}`;
  const selectionIdentityRef = useRef(selectionIdentity);
  const defaultWorkspaceId = context.workspace_options[0]?.id ?? initialLibrary.workspace.id;

  useEffect(() => { selectedRef.current = selected; }, [selected]);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; workspaceRequest.current?.abort(); validationRequest.current?.abort(); selectionGeneration.current += 1; };
  }, []);

  const invalidateSelection = useCallback(() => {
    selectionGeneration.current += 1;
    setSelected(new Map());
    setInvalidated(true);
    setError(INVALIDATION_MESSAGE);
    if (!invalidationNotified.current) { invalidationNotified.current = true; onSelectionInvalidated?.(); }
  }, [onSelectionInvalidated]);

  useEffect(() => {
    if (selectionIdentityRef.current === selectionIdentity) return;
    selectionIdentityRef.current = selectionIdentity;
    workspaceRequest.current?.abort();
    validationRequest.current?.abort();
    selectionGeneration.current += 1;
    setRevalidating(false);
    setSwitching(false);
    setView((current) => ({ revision: current.revision + 1, workspaceId: initialLibrary.workspace.id, library: initialLibrary, root: initialRoot, document: initialDocument, versionId: initialVersionId }));
    invalidateSelection();
  }, [initialDocument, initialLibrary, initialRoot, initialVersionId, invalidateSelection, selectionIdentity]);

  const browse = useCallback(async (workspaceId: string, options: Parameters<typeof browseDomainLibrary>[2] = {}) => {
    try {
      return await browseDomainLibrary(slug, workspaceId, options);
    } catch (failure) {
      if (!options.signal?.aborted && isAuthorizationFailure(failure)) invalidateSelection();
      throw failure;
    }
  }, [invalidateSelection, slug]);
  const getDocument = useCallback(async (workspaceId: string, documentId: string, signal?: AbortSignal) => {
    try {
      return await getDomainLibraryDocument(slug, workspaceId, documentId, signal);
    } catch (failure) {
      if (!signal?.aborted && isAuthorizationFailure(failure)) invalidateSelection();
      throw failure;
    }
  }, [invalidateSelection, slug]);
  const buildPath = useCallback((workspaceId: string, selection: LibrarySelection) => ragDomainFilesPath(slug, { workspaceId, folderId: selection.folderId, documentId: selection.documentId, versionId: selection.versionId }), [slug]);
  const publishSelection = useCallback((workspaceId: string, selection: LibrarySelection) => {
    if (!embedded) writeLibrarySelection(workspaceId, selection, buildPath);
  }, [buildPath, embedded]);
  const readSelection = useCallback((search: string) => {
    const selection = readLibrarySelection(search, true);
    return { ...selection, workspaceId: selection.workspaceId ?? defaultWorkspaceId };
  }, [defaultWorkspaceId]);

  const retirePendingMovement = useCallback(() => {
    // Aborting transport does not prove the move rolled back or the selection became safe.
    if (validationRequest.current || (moveObligation.current && [...moveObligation.current.selectedIds].some((id) => selectedRef.current.has(id)))) invalidateSelection();
    moveObligation.current = null;
    validationRequest.current?.abort();
    validationRequest.current = null;
    selectionGeneration.current += 1;
    setRevalidating(false);
  }, [invalidateSelection]);

  const loadWorkspace = useCallback(async (workspaceId: string, selection: LibrarySelection, publish: boolean) => {
    workspaceRequest.current?.abort();
    retirePendingMovement();
    if (!context.workspace_options.some((workspace) => workspace.id === workspaceId)) {
      setSelected(new Map());
      setError(INVALIDATION_MESSAGE);
      return;
    }
    const controller = new AbortController();
    workspaceRequest.current = controller;
    setSwitching(true);
    setError("");
    try {
      const allowedFolderIds = allowedFolderIdsByWorkspace?.[workspaceId];
      const selectedFolderId = allowedFolderIds
        ? selection.folderId && allowedFolderIds.includes(selection.folderId) ? selection.folderId : allowedFolderIds[0]
        : selection.folderId;
      if (allowedFolderIds && !selectedFolderId) throw new Error("fixed_scope_unavailable");
      const exactDocument = selection.documentId ? await getDocument(workspaceId, selection.documentId, controller.signal) : null;
      if (exactDocument && selection.folderId && exactDocument.folder_id !== selection.folderId) throw new Error("mismatched_selection");
      if (exactDocument && allowedFolderIds && (!exactDocument.folder_id || !allowedFolderIds.includes(exactDocument.folder_id))) throw new Error("fixed_scope_violation");
      const folderId = exactDocument?.folder_id ?? selectedFolderId;
      const library = await browse(workspaceId, { folderId, signal: controller.signal });
      const root = folderId ? await browse(workspaceId, { signal: controller.signal }) : library;
      if (controller.signal.aborted) return;
      setView((current) => ({ revision: current.revision + 1, workspaceId, library, root, document: exactDocument, versionId: exactDocument ? selection.versionId ?? exactDocument.active_version_id : null }));
      if (publish) publishSelection(workspaceId, { folderId, documentId: exactDocument?.id ?? null, versionId: exactDocument ? selection.versionId ?? exactDocument.active_version_id : null });
    } catch {
      if (controller.signal.aborted) return;
      invalidateSelection();
    } finally {
      if (workspaceRequest.current === controller) {
        workspaceRequest.current = null;
        setSwitching(false);
      }
    }
  }, [allowedFolderIdsByWorkspace, browse, context.workspace_options, getDocument, invalidateSelection, publishSelection, retirePendingMovement]);

  function toggleDocument(document: DocumentSummary, checked: boolean) {
    const allowedFolderIds = allowedFolderIdsByWorkspace?.[document.workspace_id];
    if (invalidated || revalidating
      || !context.workspace_options.some((workspace) => workspace.id === document.workspace_id)
      || (allowedFolderIds && (!document.folder_id || !allowedFolderIds.includes(document.folder_id)))) return;
    selectionGeneration.current += 1;
    setSelected((current) => {
      const next = new Map(current);
      if (checked) {
        if (next.size >= context.selection_limit) return current;
        next.set(document.id, document);
      } else {
        next.delete(document.id);
      }
      return next;
    });
  }

  function applySelection() {
    const documents = [...selected.values()];
    if (invalidated || revalidating || (documents.length === 0 && !allowEmptySelection)) return;
    if (onApplySelection) onApplySelection(documents);
    else router.push(ragDomainChatPath(slug, documents.map((document) => ({ workspaceId: document.workspace_id, documentId: document.id }))));
  }

  async function beforeMove(source: MoveSource, destinationId: string | null, signal: AbortSignal) {
    if (embedded || invalidated || switching || source.workspaceId !== view.workspaceId || !context.workspace_options.some((workspace) => workspace.id === source.workspaceId)) throw new Error("domain_write_unavailable");
    const fresh = source.kind === "document"
      ? documentMoveSource(await getDocument(source.workspaceId, source.id, signal))
      : await browse(source.workspaceId, { folderId: source.id, signal }).then((page) => page.folder && page.workspace.id === source.workspaceId ? folderMoveSource(page.folder, source.workspaceId) : null);
    assertMoveSourceUnchanged(source, fresh);
    const destination = await browse(source.workspaceId, { folderId: destinationId, signal });
    if (destination.workspace.id !== source.workspaceId || (destination.folder?.id ?? null) !== destinationId) throw new Error("domain_destination_changed");
    if (signal.aborted) throw new DOMException("Aborted", "AbortError");
    moveObligation.current = { source, generation: selectionGeneration.current, selectedIds: new Set([...selectedRef.current.values()].filter((document) => document.workspace_id === source.workspaceId).map((document) => document.id)) };
  }

  async function revalidateMovedSelection(source: MoveSource) {
    if (!mounted.current || selectionIdentityRef.current !== selectionIdentity) return;
    const obligation = moveObligation.current;
    if (!obligation || obligation.source !== source) return;
    if (obligation.generation !== selectionGeneration.current) {
      moveObligation.current = null;
      if ([...obligation.selectedIds].some((id) => selectedRef.current.has(id))) invalidateSelection();
      return;
    }
    const documents = [...selectedRef.current.values()];
    if (!documents.length) { moveObligation.current = null; return; }
    validationRequest.current?.abort();
    const controller = new AbortController(); validationRequest.current = controller;
    const generation = ++selectionGeneration.current;
    setRevalidating(true);
    try {
      // Read raw domain adapter here: one failed member invalidates the whole snapshot atomically.
      const fresh = await Promise.all(documents.map((document) => getDomainLibraryDocument(slug, document.workspace_id, document.id, controller.signal)));
      if (controller.signal.aborted || selectionGeneration.current !== generation) return;
      const unsafe = fresh.some((document, index) => {
        const original = documents[index];
        const allowed = allowedFolderIdsByWorkspace?.[document.workspace_id];
        return document.id !== original.id || document.workspace_id !== original.workspace_id || document.active_version_id !== original.active_version_id
          || !context.workspace_options.some((workspace) => workspace.id === document.workspace_id)
          || (allowed && (!document.folder_id || !allowed.includes(document.folder_id)));
      });
      if (unsafe) { invalidateSelection(); setError("이동으로 선택 문서의 범위 또는 활성 버전이 변경되었습니다. 문서를 다시 선택해 주세요."); }
      else { const next = new Map(fresh.map((document) => [document.id, document])); selectedRef.current = next; setSelected(next); }
    } catch {
      if (!controller.signal.aborted && selectionGeneration.current === generation) { invalidateSelection(); setError("선택 문서의 현재 위치와 권한을 확인하지 못했습니다. 문서를 다시 선택해 주세요."); }
    } finally {
      if (moveObligation.current?.source === source) moveObligation.current = null;
      if (validationRequest.current === controller) { validationRequest.current = null; if (mounted.current) setRevalidating(false); }
    }
  }

  return (
    <div className={`${styles.shell} ${embedded ? styles.embedded : ""}`}>
      {!embedded ? <div className={styles.topbar}>
        <DomainNavigation slug={slug} displayName={context.display_name} current="files" />
        <span>회사·개인 파일함</span>
      </div> : null}
      <div className={styles.selectionBar}>
        <p>{selected.size} / {context.selection_limit}개 선택</p>
        <button type="button" disabled={invalidated || revalidating || (selected.size === 0 && !allowEmptySelection) || switching} onClick={applySelection}>{actionLabel}</button>
      </div>
      {invalidated || error ? <p className={styles.error} role="alert">{error || INVALIDATION_MESSAGE}</p> : null}
      {revalidating ? <p role="status">선택 문서의 현재 위치와 활성 버전을 확인하는 중…</p> : null}
      {switching ? <p role="status">지식 공간을 불러오는 중…</p> : null}
      <DocumentBrowser
        key={`${view.workspaceId}:${view.revision}`}
        workspaceId={view.workspaceId}
        initialLibrary={view.library}
        initialRoot={view.root}
        initialWorkspaces={context.workspace_options}
        initialDocument={view.document}
        initialVersionId={view.versionId}
        readOnly={embedded || invalidated || switching || !context.workspace_options.some((workspace) => workspace.id === view.workspaceId)}
        beforeMutation={async (folderId, documentId, signal) => {
          if (embedded || invalidated || switching || !context.workspace_options.some((workspace) => workspace.id === view.workspaceId)) throw new Error("domain_write_unavailable");
          if (documentId) {
            const document = await getDocument(view.workspaceId, documentId, signal);
            if (document.folder_id !== folderId) throw new Error("document_destination_changed");
          } else await browse(view.workspaceId, { folderId, signal });
        }}
        beforeMove={beforeMove}
        onMoveCommitted={revalidateMovedSelection}
        onMoveScopeInvalidated={retirePendingMovement}
        onMoveRejected={(source) => { if (moveObligation.current?.source === source) moveObligation.current = null; }}
        onMoveUncertain={(source) => {
          if (!mounted.current || selectionIdentityRef.current !== selectionIdentity) return;
          const obligation = moveObligation.current;
          if (!obligation || obligation.source !== source) return;
          moveObligation.current = null;
          if ([...obligation.selectedIds].some((id) => selectedRef.current.has(id))) {
            invalidateSelection();
            setError("이동 결과를 확인하지 못했습니다. 현재 위치를 확인한 뒤 문서를 다시 선택해 주세요.");
          }
        }}
        showMemberManagement={!embedded}
        showEvidenceApproval={!embedded}
        browse={browse}
        getDocument={getDocument}
        writeSelection={publishSelection}
        readSelection={readSelection}
        navigationEnabled={!embedded}
        onRestoreWorkspace={(workspaceId, selection) => void loadWorkspace(workspaceId, selection, false)}
        onSelectWorkspace={(workspaceId) => void loadWorkspace(workspaceId, { folderId: null, documentId: null, versionId: null }, true)}
        selectedDocumentIds={invalidated ? new Set() : new Set(selected.keys())}
        onToggleDocumentSelection={toggleDocument}
        isDocumentSelectionDisabled={(document) => invalidated || revalidating || (selected.size >= context.selection_limit && !selected.has(document.id))}
        isFolderSelectionDisabled={(folderId) => {
          const allowedFolderIds = allowedFolderIdsByWorkspace?.[view.workspaceId];
          return allowedFolderIds ? folderId === null || !allowedFolderIds.includes(folderId) : false;
        }}
        backHref={null}
        browserDescription="도메인에 연결되고 현재 권한이 허용한 원본을 읽고 선택합니다."
      />
    </div>
  );
}

function isAuthorizationFailure(failure: unknown): boolean {
  return failure instanceof ApiError && [401, 403, 404].includes(failure.status);
}
