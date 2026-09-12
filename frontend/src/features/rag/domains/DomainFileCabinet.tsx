"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { DocumentBrowser } from "../../assets/DocumentBrowser";
import type { DocumentSummary, LibraryPage } from "../../assets/api";
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
}: DomainFileCabinetProps) {
  const router = useRouter();
  const [view, setView] = useState<CabinetView>({ revision: 0, workspaceId: initialLibrary.workspace.id, library: initialLibrary, root: initialRoot, document: initialDocument, versionId: initialVersionId });
  const [selected, setSelected] = useState(() => new Map(initialSelectedDocuments.map((document) => [document.id, document])));
  const [switching, setSwitching] = useState(false);
  const [error, setError] = useState("");
  const [invalidated, setInvalidated] = useState(false);
  const workspaceRequest = useRef<AbortController | null>(null);
  const selectionIdentity = `${slug}:${context.domain_id}:${context.connection_version_id}`;
  const selectionIdentityRef = useRef(selectionIdentity);
  const defaultWorkspaceId = context.workspace_options[0]?.id ?? initialLibrary.workspace.id;

  useEffect(() => () => workspaceRequest.current?.abort(), []);

  const invalidateSelection = useCallback(() => {
    setSelected(new Map());
    setInvalidated(true);
    setError(INVALIDATION_MESSAGE);
  }, []);

  useEffect(() => {
    if (selectionIdentityRef.current === selectionIdentity) return;
    selectionIdentityRef.current = selectionIdentity;
    workspaceRequest.current?.abort();
    setSwitching(false);
    setView((current) => ({ revision: current.revision + 1, workspaceId: initialLibrary.workspace.id, library: initialLibrary, root: initialRoot, document: initialDocument, versionId: initialVersionId }));
    invalidateSelection();
  }, [initialDocument, initialLibrary, initialRoot, initialVersionId, invalidateSelection, selectionIdentity]);

  const browse = useCallback(async (workspaceId: string, options: Parameters<typeof browseDomainLibrary>[2] = {}) => {
    try {
      return await browseDomainLibrary(slug, workspaceId, options);
    } catch (failure) {
      if (isAuthorizationFailure(failure)) invalidateSelection();
      throw failure;
    }
  }, [invalidateSelection, slug]);
  const getDocument = useCallback(async (workspaceId: string, documentId: string, signal?: AbortSignal) => {
    try {
      return await getDomainLibraryDocument(slug, workspaceId, documentId, signal);
    } catch (failure) {
      if (isAuthorizationFailure(failure)) invalidateSelection();
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

  const loadWorkspace = useCallback(async (workspaceId: string, selection: LibrarySelection, publish: boolean) => {
    workspaceRequest.current?.abort();
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
  }, [allowedFolderIdsByWorkspace, browse, context.workspace_options, getDocument, invalidateSelection, publishSelection]);

  function toggleDocument(document: DocumentSummary, checked: boolean) {
    const allowedFolderIds = allowedFolderIdsByWorkspace?.[document.workspace_id];
    if (invalidated
      || !context.workspace_options.some((workspace) => workspace.id === document.workspace_id)
      || (allowedFolderIds && (!document.folder_id || !allowedFolderIds.includes(document.folder_id)))) return;
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
    if (invalidated || (documents.length === 0 && !allowEmptySelection)) return;
    if (onApplySelection) onApplySelection(documents);
    else router.push(ragDomainChatPath(slug, documents.map((document) => ({ workspaceId: document.workspace_id, documentId: document.id }))));
  }

  return (
    <div className={`${styles.shell} ${embedded ? styles.embedded : ""}`}>
      {!embedded ? <div className={styles.topbar}>
        <DomainNavigation slug={slug} displayName={context.display_name} current="files" />
        <span>회사·개인 파일함</span>
      </div> : null}
      <div className={styles.selectionBar}>
        <p>{selected.size} / {context.selection_limit}개 선택</p>
        <button type="button" disabled={invalidated || (selected.size === 0 && !allowEmptySelection) || switching} onClick={applySelection}>{actionLabel}</button>
      </div>
      {invalidated || error ? <p className={styles.error} role="alert">{invalidated ? INVALIDATION_MESSAGE : error}</p> : null}
      {switching ? <p role="status">지식 공간을 불러오는 중…</p> : null}
      <DocumentBrowser
        key={`${view.workspaceId}:${view.revision}`}
        workspaceId={view.workspaceId}
        initialLibrary={view.library}
        initialRoot={view.root}
        initialWorkspaces={context.workspace_options}
        initialDocument={view.document}
        initialVersionId={view.versionId}
        readOnly
        showMemberManagement={!embedded}
        browse={browse}
        getDocument={getDocument}
        writeSelection={publishSelection}
        readSelection={readSelection}
        navigationEnabled={!embedded}
        onRestoreWorkspace={(workspaceId, selection) => void loadWorkspace(workspaceId, selection, false)}
        onSelectWorkspace={(workspaceId) => void loadWorkspace(workspaceId, { folderId: null, documentId: null, versionId: null }, true)}
        selectedDocumentIds={invalidated ? new Set() : new Set(selected.keys())}
        onToggleDocumentSelection={toggleDocument}
        isDocumentSelectionDisabled={(document) => invalidated || (selected.size >= context.selection_limit && !selected.has(document.id))}
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
  return failure instanceof ApiError && (failure.status === 403 || failure.status === 404);
}
