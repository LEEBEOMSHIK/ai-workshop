"use client";

import { type KeyboardEvent as ReactKeyboardEvent, useEffect, useRef, useState } from "react";

import type { DocumentSummary, LibraryPage } from "../../assets/api";
import { DomainFileCabinet } from "../domains/DomainFileCabinet";
import { browseDomainLibrary, getDomainLibraryContext, type DomainLibraryContext } from "../domains/library-api";
import type { Folder } from "./api";
import styles from "./DocumentSelectionPanel.module.css";

interface PanelData {
  context: DomainLibraryContext;
  library: LibraryPage;
  root: LibraryPage;
  allowedFolderIdsByWorkspace?: Readonly<Record<string, readonly string[]>>;
}

export function DocumentSelectionPanel({ slug, currentDocuments, workspaceIds, folderIds, foldersByWorkspace, onApply, onClose, returnFocus, onSelectionInvalidated }: {
  slug: string;
  currentDocuments: DocumentSummary[];
  workspaceIds: string[];
  folderIds: string[];
  foldersByWorkspace: Record<string, Folder[]>;
  onApply: (documents: DocumentSummary[]) => void;
  onClose: () => void;
  returnFocus: HTMLElement | null;
  onSelectionInvalidated?: () => void;
}) {
  const [data, setData] = useState<PanelData | null>(null);
  const [error, setError] = useState(false);
  const panelRef = useRef<HTMLElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const controller = new AbortController();
    void getDomainLibraryContext(slug, controller.signal).then(async (context) => {
      const allowedWorkspaceIds = new Set(workspaceIds.length > 0 ? workspaceIds : context.workspace_options.map(({ id }) => id));
      const allowedFolderIds = new Set(folderIds);
      const folderBoundary = folderIds.length > 0
        ? Object.fromEntries(workspaceIds.map((workspaceId) => [
          workspaceId,
          (foldersByWorkspace[workspaceId] ?? []).filter((folder) => allowedFolderIds.has(folder.id)).map((folder) => folder.id),
        ]))
        : undefined;
      const workspaceOptions = context.workspace_options.filter((workspace) => allowedWorkspaceIds.has(workspace.id)
        && (!folderBoundary || folderBoundary[workspace.id]?.length));
      const scopedContext = { ...context, workspace_options: workspaceOptions };
      const workspaceId = currentDocuments.find((document) => workspaceOptions.some((workspace) => workspace.id === document.workspace_id))?.workspace_id
        ?? workspaceOptions[0]?.id;
      if (!workspaceId
        || currentDocuments.some((document) => !workspaceOptions.some((workspace) => workspace.id === document.workspace_id)
          || (folderBoundary && (!document.folder_id || !folderBoundary[document.workspace_id]?.includes(document.folder_id))))) throw new Error("library_unavailable");
      const root = await browseDomainLibrary(slug, workspaceId, { signal: controller.signal });
      const initialFolderId = folderBoundary?.[workspaceId]?.[0] ?? null;
      const library = initialFolderId
        ? await browseDomainLibrary(slug, workspaceId, { folderId: initialFolderId, signal: controller.signal })
        : root;
      if (!controller.signal.aborted) setData({ context: scopedContext, library, root, allowedFolderIdsByWorkspace: folderBoundary });
    }).catch(() => {
      if (!controller.signal.aborted) setError(true);
    });
    return () => controller.abort();
  }, [currentDocuments, folderIds, foldersByWorkspace, slug, workspaceIds]);

  useEffect(() => {
    closeButtonRef.current?.focus();
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = previousOverflow; };
  }, []);

  function close() {
    if (panelRef.current?.querySelector('[role="dialog"][aria-busy="true"]')) return;
    onClose();
    queueMicrotask(() => returnFocus?.focus());
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab" || !panelRef.current) return;
    const controls = focusableElements(panelRef.current);
    const first = controls[0];
    const last = controls.at(-1);
    if (!first || !last) {
      event.preventDefault();
      return;
    }
    if (event.shiftKey && (document.activeElement === first || !panelRef.current.contains(document.activeElement))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (document.activeElement === last || !panelRef.current.contains(document.activeElement))) {
      event.preventDefault();
      first.focus();
    }
  }

  return <div className={styles.backdrop}>
    <section ref={panelRef} className={styles.panel} role="dialog" aria-modal="true" aria-labelledby="document-selection-title" onKeyDown={handleKeyDown}>
      <header className={styles.header}>
        <h2 id="document-selection-title">파일 선택</h2>
        <button ref={closeButtonRef} type="button" onClick={close}>닫기</button>
      </header>
      <div className={styles.body}>
      <p className={styles.description}>답변의 근거로 사용할 문서를 선택하세요.</p>
      {error ? <p className={styles.error} role="alert">도메인 파일함을 불러오지 못했습니다. 현재 선택은 유지됩니다.</p> : null}
      {!data && !error ? <p role="status">도메인 파일함을 불러오는 중…</p> : null}
      {data ? <DomainFileCabinet
        slug={slug}
        context={data.context}
        initialLibrary={data.library}
        initialRoot={data.root}
        initialDocument={null}
        initialVersionId={null}
        initialSelectedDocuments={currentDocuments}
        actionLabel="선택 적용"
        allowEmptySelection={currentDocuments.length > 0}
        embedded
        allowedFolderIdsByWorkspace={data.allowedFolderIdsByWorkspace}
        onApplySelection={(documents) => { onApply(documents); close(); }}
        onSelectionInvalidated={onSelectionInvalidated}
      /> : null}
      </div>
    </section>
  </div>;
}

function focusableElements(container: HTMLElement): HTMLElement[] {
  return Array.from(container.querySelectorAll<HTMLElement>(
    'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )).filter((element) => !element.hasAttribute("hidden") && element.getAttribute("aria-hidden") !== "true");
}
