"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";
import { ApiError } from "../../shared/api/client";
import { browseLibrary, getLibraryDocument, type LibraryPage } from "./api";
import { assertMoveSourceUnchanged, documentMoveSource, folderMoveSource, moveDestinationProblem, movementError, type MoveResult, type MoveSource } from "./movement";
import type { PendingMove } from "./useAssetMovement";
import styles from "./MoveDialog.module.css";

interface Props {
  pending: PendingMove;
  writable: boolean;
  browse: typeof browseLibrary;
  getDocument: typeof getLibraryDocument;
  execute: (source: MoveSource, destination: LibraryPage, signal: AbortSignal, committed: (result: MoveResult) => void) => Promise<void>;
  reconcile: (source: MoveSource, result: MoveResult | null, signal: AbortSignal) => Promise<void>;
  onFailure: (failure: unknown) => void;
  onClose: () => void;
  fallbackFocus: () => HTMLElement | null;
}

export function MoveDialog({ pending, writable, browse, getDocument, execute, reconcile, onFailure, onClose, fallbackFocus }: Props) {
  const [source, setSource] = useState(pending.source);
  const [destinationId, setDestinationId] = useState(pending.destinationId);
  const [destination, setDestination] = useState<LibraryPage | null>(null);
  const [origin, setOrigin] = useState<LibraryPage | null>(null);
  const [reading, setReading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [needsRefresh, setNeedsRefresh] = useState(false);
  const [outcome, setOutcome] = useState<"draft" | "committed" | "uncertain">("draft");
  const resultRef = useRef<MoveResult | null>(null);
  const submitLock = useRef(false);
  const controllerRef = useRef<AbortController | null>(null);
  const readRef = useRef<AbortController | null>(null);
  const panel = useRef<HTMLElement>(null);
  const cancel = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const problem = moveDestinationProblem(source, destination);

  useEffect(() => {
    cancel.current?.focus();
    return () => { controllerRef.current?.abort(); readRef.current?.abort(); };
  }, []);

  useEffect(() => {
    if (busy) panel.current?.focus();
    else if (!reading && (!panel.current?.contains(document.activeElement) || document.activeElement === panel.current)) cancel.current?.focus();
  }, [reading, busy, destination]);

  useEffect(() => {
    const controller = new AbortController(); readRef.current?.abort(); readRef.current = controller;
    void Promise.all([
      browse(source.workspaceId, { folderId: destinationId, signal: controller.signal }),
      browse(source.workspaceId, { folderId: source.parentId, signal: controller.signal }),
    ]).then(([next, parent]) => {
      if (controller.signal.aborted) return;
      if ((next.folder?.id ?? null) !== destinationId || next.workspace.id !== source.workspaceId || (parent.folder?.id ?? null) !== source.parentId) throw new Error("invalid_destination");
      setDestination(next); setOrigin(parent);
    }).catch((failure) => { if (!controller.signal.aborted) { onFailure(failure); setError(movementError(failure)); setNeedsRefresh(true); } })
      .finally(() => { if (!controller.signal.aborted) setReading(false); });
    return () => controller.abort();
    // onFailure is a notification, not a read identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [browse, destinationId, source.workspaceId, source.parentId]);

  function navigateDestination(folderId: string | null) {
    if (folderId === destinationId) return;
    setReading(true); setDestination(null); setDestinationId(folderId);
  }

  async function readSource(signal: AbortSignal): Promise<MoveSource | null> {
    if (source.kind === "document") return documentMoveSource(await getDocument(source.workspaceId, source.id, signal));
    const page = await browse(source.workspaceId, { folderId: source.id, signal });
    return page.folder && page.workspace.id === source.workspaceId ? folderMoveSource(page.folder, source.workspaceId) : null;
  }

  function close() {
    if (submitLock.current) return;
    onClose();
    queueMicrotask(() => (pending.opener?.isConnected ? pending.opener : fallbackFocus())?.focus());
  }

  async function refresh() {
    if (submitLock.current) return;
    submitLock.current = true; setBusy(true); setError("");
    const controller = new AbortController(); controllerRef.current = controller;
    try {
      if (outcome !== "draft") {
        await reconcile(source, resultRef.current, controller.signal);
        if (!controller.signal.aborted) { submitLock.current = false; close(); }
      } else {
        const fresh = await readSource(controller.signal);
        if (!fresh) throw new Error("missing_revision");
        const [next, parent] = await Promise.all([
          browse(source.workspaceId, { folderId: destinationId, signal: controller.signal }),
          browse(source.workspaceId, { folderId: fresh.parentId, signal: controller.signal }),
        ]);
        if (controller.signal.aborted) return;
        if (fresh.id !== source.id || fresh.workspaceId !== source.workspaceId || (next.folder?.id ?? null) !== destinationId) throw new Error("invalid_destination");
        setSource(fresh); setDestination(next); setOrigin(parent); setNeedsRefresh(false);
      }
    } catch (failure) { if (!controller.signal.aborted) { onFailure(failure); setError(outcome === "committed" ? "이동 완료, 목록 새로고침 필요" : movementError(failure)); } }
    finally { submitLock.current = false; if (!controller.signal.aborted) setBusy(false); }
  }

  async function submit() {
    if (submitLock.current || !writable || problem || !destination || needsRefresh || outcome !== "draft") return;
    submitLock.current = true; setBusy(true); setError("");
    const controller = new AbortController(); controllerRef.current = controller;
    let committed = false;
    try {
      const fresh = await readSource(controller.signal);
      assertMoveSourceUnchanged(source, fresh);
      const page = await browse(source.workspaceId, { folderId: destinationId, signal: controller.signal });
      if (controller.signal.aborted) return;
      if ((page.folder?.id ?? null) !== destinationId) throw new Error("invalid_destination");
      const issue = moveDestinationProblem(source, page);
      if (issue) { setDestination(page); setError(issue); return; }
      await execute(source, page, controller.signal, (result) => {
        committed = true; resultRef.current = result; setOutcome("committed");
      });
      if (controller.signal.aborted) return;
      submitLock.current = false; close();
    } catch (failure) {
      if (controller.signal.aborted) return;
      onFailure(failure);
      if (committed) { setError("이동 완료, 목록 새로고침 필요"); }
      else {
        setError(movementError(failure)); setNeedsRefresh(true);
        // The execute boundary marks network ambiguity only once POST was sent.
        if (failure instanceof MoveOutcomeUnknown) setOutcome("uncertain");
      }
    } finally { submitLock.current = false; if (!controller.signal.aborted) setBusy(false); }
  }

  async function moreFolders() {
    if (reading || !destination?.next_folder_cursor || submitLock.current) return;
    const cursor = destination.next_folder_cursor;
    const controller = new AbortController(); readRef.current?.abort(); readRef.current = controller;
    setReading(true);
    try {
      const page = await browse(source.workspaceId, { folderId: destinationId, folderCursor: cursor, signal: controller.signal });
      if (controller.signal.aborted) return;
      setDestination((current) => current && current.next_folder_cursor === cursor ? { ...current, folders: [...new Map([...current.folders, ...page.folders].map((folder) => [folder.id, folder])).values()], next_folder_cursor: page.next_folder_cursor } : current);
    } catch (failure) { if (!controller.signal.aborted) { onFailure(failure); setError(movementError(failure)); } }
    finally { if (!controller.signal.aborted) setReading(false); }
  }

  function keyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(); }
    if (event.key !== "Tab") return;
    event.stopPropagation();
    const controls = Array.from(panel.current?.querySelectorAll<HTMLElement>('button:not([disabled]), [tabindex="0"]') ?? []);
    const first = controls[0]; const last = controls.at(-1);
    if (!first || !last) { event.preventDefault(); return; }
    if (event.shiftKey && (document.activeElement === first || !panel.current?.contains(document.activeElement))) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && (document.activeElement === last || !panel.current?.contains(document.activeElement))) { event.preventDefault(); first.focus(); }
  }

  return <div className={styles.backdrop} onDrop={(event) => event.preventDefault()} onDragOver={(event) => event.preventDefault()}>
    <section ref={panel} tabIndex={-1} className={styles.dialog} role="dialog" aria-modal="true" aria-labelledby={titleId} aria-busy={busy} onKeyDown={keyDown}>
      <h2 id={titleId}>이동 확인</h2>
      <header className={styles.objectHeader} role="group" aria-label="이동할 객체">
        <span className={styles.objectType}>{source.kind === "document" ? "문서" : "폴더"}</span>
        <strong className={styles.objectName}>{source.name}</strong>
      </header>
      <div className={styles.locations}>
        <LocationSummary label="출발지" page={origin} />
        <LocationSummary label="목적지" page={destination} />
      </div>
      {outcome === "draft" ? <>
        <section className={styles.destinationBrowser} aria-label="목적지 선택">
          <h3>목적지 선택</h3>
          <nav className={styles.breadcrumbs} aria-label="이동 목적지 경로">
            <button type="button" disabled={busy || reading} onClick={() => navigateDestination(null)}>root</button>
            {destination?.ancestors.map((folder, index) => <button key={folder.id} type="button" disabled={busy || reading} aria-label={`root / ${destination.ancestors.slice(0, index + 1).map((ancestor) => ancestor.name).join(" / ")} 상위 폴더 열기`} onClick={() => navigateDestination(folder.id)}>{folder.name}</button>)}
          </nav>
          <ul className={styles.folders}>{destination?.folders.map((folder) => <li key={folder.id}><button type="button" disabled={busy || reading || (source.kind === "folder" && (folder.id === source.id || destination.ancestors.some((ancestor) => ancestor.id === source.id) || destination.folder?.id === source.id))} aria-label={`${folder.name} 목적지 열기`} onClick={() => navigateDestination(folder.id)}>{folder.name}</button></li>)}</ul>
          {destination?.next_folder_cursor ? <button type="button" disabled={busy || reading} onClick={moreFolders}>목적지 폴더 더 보기</button> : null}
          {problem && !reading ? <p role="status">{problem}</p> : null}
        </section>
      </> : null}
      {reading ? <p role="status">이동 위치를 불러오는 중…</p> : null}
      {busy ? <p role="status">{outcome === "draft" ? "이동을 확인하고 저장하는 중… 창을 닫아도 서버 작업을 취소한 것으로 간주하지 않습니다." : "목록을 확인하는 중…"}</p> : null}
      {error ? <p role="alert">{error}</p> : null}
      <div className={styles.actions} role="group" aria-label="이동 작업">
        <button ref={cancel} type="button" disabled={busy} onClick={close}>{outcome === "draft" ? "이동 취소" : "닫기"}</button>
        {outcome !== "draft" ? <button className={styles.primaryAction} type="button" disabled={busy} onClick={refresh}>목록 새로고침</button> : needsRefresh ? <button className={styles.primaryAction} type="button" disabled={busy || !writable} onClick={refresh}>이동 정보 새로 불러오기</button> : <button className={styles.primaryAction} type="button" disabled={busy || reading || !writable || !!problem} onClick={submit}>여기로 이동</button>}
      </div>
    </section>
  </div>;
}

export class MoveOutcomeUnknown extends Error {}

export function isUnknownMoveFailure(failure: unknown) { return !(failure instanceof ApiError) || failure.status >= 500; }

function LocationSummary({ label, page }: { label: "출발지" | "목적지"; page: LibraryPage | null }) {
  return <section className={styles.location} aria-label={label}>
    <h3>{label}</h3>
    <dl>
      <div><dt>작업 공간</dt><dd>{page?.workspace.name ?? "확인 중…"}</dd></div>
      <div><dt>폴더 경로</dt><dd>{page ? folderPathLabel(page) : "확인 중…"}</dd></div>
    </dl>
  </section>;
}

function folderPathLabel(page: LibraryPage) { return ["root", ...page.ancestors.map((folder) => folder.name), ...(page.folder ? [page.folder.name] : [])].join(" / "); }
