"use client";

import Link from "next/link";
import {
  type FormEvent,
  type KeyboardEvent,
  useEffect,
  useRef,
  useState,
} from "react";

import { ApiError } from "../../../shared/api/client";
import { routes } from "../../../shared/routing/routes";
import type { DocumentSummary } from "../../assets/api";
import { LibraryViewer } from "../../assets/LibraryViewer";
import type { Domain } from "../domains/api";
import { DomainNavigation } from "../domains/DomainNavigation";
import { getDomainLibraryDocument } from "../domains/library-api";
import {
  type Evidence,
  type Folder,
  listConversationFolders,
} from "./api";
import { ConversationAnswer } from "./ConversationAnswer";
import { EvidencePanel } from "./EvidencePanel";
import { ProcessingDisclosure } from "./ProcessingDisclosure";
import { CodexQuestionConsent } from "./CodexQuestionConsent";
import { DocumentSelectionPanel } from "./DocumentSelectionPanel";
import { buildScopeSnapshot, ScopeSelector } from "./ScopeSelector";
import { selectionFromDocuments, type ScopeMode, type ScopeSnapshot, type Selection, type TranscriptItem } from "./types";

import { cancelConversationTurn, createConversation, deleteConversation, getConversation, listConversations, renameConversation, sendConversationTurn, type ConversationDetail, type ConversationSummary, type TurnRequest } from "./sessions-api";
import { ConversationAttachments } from "./ConversationAttachments";

export function ConversationPage({ domain, initialSelection = null, initialWorkspaceIds = [] }: { domain: Domain; initialSelection?: Selection; initialWorkspaceIds?: string[] }) {
  const preview = domain.generation_execution_preview;
  const sessionKey = JSON.stringify([domain.id, domain.connection_version?.id, preview, domain.workspace_options, initialSelection?.documentIds, initialWorkspaceIds]);
  return <ConversationSession key={sessionKey} domain={domain} initialSelection={initialSelection} initialWorkspaceIds={initialWorkspaceIds} />;
}

function ConversationSession({ domain, initialSelection, initialWorkspaceIds }: { domain: Domain; initialSelection: Selection; initialWorkspaceIds: string[] }) {
  const [selection, setSelection] = useState<Selection>(initialSelection);
  const selectionRef = useRef(selection);
  function updateSelection(value: Selection) { selectionRef.current = value; setSelection(value); }
  const [knownDocuments, setKnownDocuments] = useState<DocumentSummary[]>(initialSelection?.documents ?? []);
  const [scopeMode, setScopeMode] = useState<ScopeMode>(initialSelection === null ? "workspace" : "documents");
  const [workspaceIds, setWorkspaceIds] = useState(() => initialSelection === null
    ? domain.workspace_options.filter(({ id }) => initialWorkspaceIds.includes(id)).map(({ id }) => id)
    : unique(initialSelection.documents.map(({ workspace_id }) => workspace_id)));
  const [folderIds, setFolderIds] = useState<string[]>([]);
  const [foldersByWorkspace, setFoldersByWorkspace] = useState<Record<string, Folder[]>>({});
  const [scopeOpen, setScopeOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [sessions, setSessions] = useState<ConversationSummary[]>([]);
  const [session, setSession] = useState<ConversationDetail | null>(null);
  const sessionRef = useRef<ConversationDetail | null>(null);
  const [sessionLoading, setSessionLoading] = useState(false);
  const [sessionError, setSessionError] = useState("");
  const [editingTitle, setEditingTitle] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [attachmentMenuOpen, setAttachmentMenuOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [draggingFiles, setDraggingFiles] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const questionRef = useRef<HTMLTextAreaElement>(null);
  const dragDepth = useRef(0);
  const [attachmentBusy, setAttachmentBusy] = useState(false);
  const pendingRequest = useRef<{sessionId: string; request: TurnRequest} | null>(null);
  const creatingSession = useRef<Promise<ConversationDetail> | null>(null);
  const [transcript, setTranscript] = useState<TranscriptItem[]>([]);
  const [pendingQuery, setPendingQuery] = useState("");
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const [retryQuery, setRetryQuery] = useState("");
  const [requiresDomainReentry, setRequiresDomainReentry] = useState(false);
  const [requiresScopeRevision, setRequiresScopeRevision] = useState(false);
  const [requiresContextReset, setRequiresContextReset] = useState(false);
  const [externalConfirmed, setExternalConfirmed] = useState(false);
  const [classification, setClassification] = useState<"" | "public" | "synthetic">("");
  const [selectedEvidence, setSelectedEvidence] = useState<Evidence | null>(null);
  const [folderError, setFolderError] = useState(false);
  const [selectionPanelOpen, setSelectionPanelOpen] = useState(false);
  const [selectedOriginal, setSelectedOriginal] = useState<{ document: DocumentSummary; versionId: string } | null>(null);
  const requestGeneration = useRef(0);
  const requestController = useRef<AbortController | null>(null);
  const composing = useRef(false);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const transcriptEndRef = useRef<HTMLDivElement>(null);
  const stickToBottom = useRef(true);
  const returnFocus = useRef<HTMLElement | null>(null);
  const attachmentButtonRef = useRef<HTMLButtonElement>(null);
  const [selectionReturnFocus, setSelectionReturnFocus] = useState<HTMLElement | null>(null);
  const originalReturnFocus = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const textarea = questionRef.current;
    if (textarea) { textarea.style.height = "auto"; textarea.style.height = `${Math.min(textarea.scrollHeight, 120)}px`; }
  }, [query]);

  useEffect(() => {
    if (!attachmentMenuOpen) return;
    function closeOutside(event: PointerEvent) {
      if (event.target instanceof Node && !menuRef.current?.contains(event.target)) setAttachmentMenuOpen(false);
    }
    function closeEscape(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") { setAttachmentMenuOpen(false); attachmentButtonRef.current?.focus(); }
    }
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeEscape);
    return () => { document.removeEventListener("pointerdown", closeOutside); document.removeEventListener("keydown", closeEscape); };
  }, [attachmentMenuOpen]);

  function receiveFiles(files: File[]) {
    if (!files.length || searching || sessionLoading || requiresDomainReentry || attachmentBusy) return;
    setPendingFiles(current => [...current, ...files]);
    setUploadOpen(true);
    setExternalConfirmed(false);
    setAttachmentMenuOpen(false);
  }

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all(domain.workspace_options.map(async (workspace) => {
      const folders = await listConversationFolders(workspace.id, controller.signal);
      return [workspace.id, folders] as const;
    })).then((entries) => {
      setFoldersByWorkspace(Object.fromEntries(entries));
      setFolderError(false);
    }).catch(() => {
      if (!controller.signal.aborted) setFolderError(true);
    });
    return () => controller.abort();
  }, [domain.workspace_options]);

  useEffect(() => () => {
    requestGeneration.current += 1;
    requestController.current?.abort();
  }, []);

  useEffect(() => {
    if (stickToBottom.current) transcriptEndRef.current?.scrollIntoView?.({ block: "end" });
  }, [pendingQuery, transcript]);

  useEffect(() => {
    const controller = new AbortController();
    void listConversations(domain.slug, controller.signal).then(rows => {
      if (!controller.signal.aborted) setSessions(current => [...current, ...rows.filter(row => !current.some(item => item.id === row.id))]);
    }).catch(() => {
      if (!controller.signal.aborted) setSessionError("대화 목록을 불러오지 못했습니다.");
    });
    const id = new URL(window.location.href).searchParams.get("conversation");
    if (id) void selectSession(id);
    const onPopState = () => {
      const selected = new URL(window.location.href).searchParams.get("conversation");
      if (selected) void selectSession(selected); else startNewConversation();
    };
    window.addEventListener("popstate", onPopState);
    return () => { controller.abort(); window.removeEventListener("popstate", onPopState); };
    // This component is remounted when the domain or connection changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [domain.slug]);

  const externalProcessing = domain.generation_execution_preview?.external_transfer === true;
  const codexProcessing = domain.generation_execution_preview?.provider === "development_codex_exec";
  const canSend = domain.ready
    && domain.connection_version !== null
    && domain.generation_execution_preview !== null
    && workspaceIds.length > 0
    && (scopeMode !== "folder" || folderIds.length > 0)
    && (scopeMode !== "folder" || !folderError)
    && (scopeMode !== "documents" || (selection !== null && selection.documentIds.length > 0))
    && query.trim().length >= 2
    && !searching
    && !sessionLoading
    && !attachmentBusy
    && !session?.turns.some(turn => turn.status === "running" || (turn.status === "cancelled" && !turn.execution_terminated))
    && !requiresDomainReentry
    && !requiresScopeRevision
    && !requiresContextReset
    && !selectionPanelOpen
    && (!externalProcessing || externalConfirmed)
    && (!codexProcessing || (classification !== "" && !!domain.generation_execution_preview?.disclosure_version));

  function markScopeChange(): boolean {
    if (searching) return false;
    pendingRequest.current = null;
    setExternalConfirmed(false);
    setClassification("");
    setError("");
    setRetryQuery("");
    setRequiresScopeRevision(false);
    setRequiresContextReset(false);
    setTranscript((current) => {
      if ((!session?.turns.length && !current.some((item) => item.type === "answer")) || current.at(-1)?.type === "scope-divider") {
        return current;
      }
      return [...current, { type: "scope-divider", key: Date.now() }];
    });
    return true;
  }

  function applyScope(mode: Exclude<ScopeMode, "documents">, nextWorkspaceIds: string[], nextFolderIds: string[]) {
    if (!markScopeChange()) return;
    setScopeMode(mode); updateSelection(null); setWorkspaceIds(nextWorkspaceIds); setFolderIds(nextFolderIds); setScopeOpen(false);
  }

  function currentScope(): ScopeSnapshot {
    return buildScopeSnapshot(domain, workspaceIds, folderIds, foldersByWorkspace, selection);
  }

  function saveSession(detail: ConversationDetail) {
    sessionRef.current = detail;
    setSession(detail);
    setSessions(current => [detail, ...current.filter(item => item.id !== detail.id)]);
  }

  function updateUrl(id: string | null) {
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("conversation", id); else url.searchParams.delete("conversation");
    window.history.replaceState(null, "", url);
  }

  async function ensureSession() {
    if (sessionRef.current) return sessionRef.current;
    const generation = requestGeneration.current;
    if (!creatingSession.current) creatingSession.current = createConversation(domain.slug);
    const creation = creatingSession.current;
    try {
      const created = await creation;
      if (requestGeneration.current === generation) { saveSession(created); updateUrl(created.id); }
      return created;
    } finally { if (creatingSession.current === creation) creatingSession.current = null; }
  }

  async function selectSession(id: string) {
    requestGeneration.current += 1;
    const generation = requestGeneration.current;
    requestController.current?.abort();
    setSearching(false); setPendingQuery(""); setTranscript([]); setSession(null); sessionRef.current = null;
    setKnownDocuments([]);
    pendingRequest.current = null;
    setQuery(""); setError(""); setRetryQuery(""); setSessionError(""); setSessionLoading(true);
    setExternalConfirmed(false); setClassification(""); setSelectedEvidence(null); setSelectedOriginal(null);
    setRequiresContextReset(false); setRequiresScopeRevision(false); setRequiresDomainReentry(false);
    setEditingTitle(null); setConfirmDelete(false); setUploadOpen(false); setPendingFiles([]); setDraggingFiles(false); dragDepth.current = 0; setAttachmentMenuOpen(false);
    updateUrl(id);
    try {
      const detail = await getConversation(domain.slug, id);
      if (requestGeneration.current !== generation) return;
      saveSession(detail);
      const last = detail.turns.filter(turn => !turn.redacted).at(-1);
      if (last?.request_scope) {
        setWorkspaceIds(last.request_scope.workspace_ids); setFolderIds(last.request_scope.folder_ids ?? []);
        const ids = last.request_scope.document_ids ?? null;
        updateSelection(ids === null ? null : {documentIds: ids, documentNames: [], documents: []});
        setScopeMode(ids !== null ? "documents" : last.request_scope.folder_ids?.length ? "folder" : "workspace");
        if (ids?.length) {
          const workspaces = last.request_scope.workspace_ids;
          const documents = await Promise.all(ids.map(async documentId => {
            for (const workspaceId of workspaces) {
              try { return await getDomainLibraryDocument(domain.slug, workspaceId, documentId); }
              catch (caught) { if (!(caught instanceof ApiError) || caught.status !== 404) throw caught; }
            }
            throw new Error("selected_document_unavailable");
          }));
          if (requestGeneration.current !== generation) return;
          updateSelection(selectionFromDocuments(documents)); setKnownDocuments(documents);
        }
      } else { updateSelection(null); setWorkspaceIds([]); setFolderIds([]); setScopeMode("workspace"); }
    } catch { if (requestGeneration.current === generation) { setSessionError("대화 또는 선택 문서를 불러오지 못했습니다. 접근 권한과 연결 상태를 확인해 주세요."); setRequiresScopeRevision(true); } }
    finally { if (requestGeneration.current === generation) setSessionLoading(false); }
  }

  async function editTitle() {
    if (!session || !editingTitle?.trim()) return;
    const generation = requestGeneration.current;
    try { const detail = await renameConversation(domain.slug, session, editingTitle.trim()); if (requestGeneration.current === generation) { saveSession(detail); setEditingTitle(null); } }
    catch { setSessionError("대화 제목을 저장하지 못했습니다. 대화를 다시 열어 최신 상태를 확인해 주세요."); }
  }

  async function removeSession() {
    if (!session) return;
    const generation = requestGeneration.current;
    try {
      const current = searching || session.turns.some(turn => turn.status === "running")
        ? await getConversation(domain.slug, session.id) : session;
      await deleteConversation(domain.slug, current);
      setSessions(current => current.filter(item => item.id !== session.id));
      if (requestGeneration.current === generation) startNewConversation();
    } catch { setSessionError("대화를 삭제하지 못했습니다. 대화를 다시 열어 최신 상태를 확인해 주세요."); }
  }

  async function sendQuestion(question: string) {
    const normalized = question.trim();
    const scope = currentScope();
    if (
      normalized.length < 2
      || searching || sessionLoading || attachmentBusy
      || !domain.ready
      || !domain.connection_version
      || !domain.generation_execution_preview
      || scope.workspaceIds.length === 0
      || requiresDomainReentry
      || requiresScopeRevision
      || requiresContextReset
      || (scopeMode === "folder" && scope.folderIds.length === 0)
      || (scopeMode === "folder" && folderError)
      || (scopeMode === "documents" && (scope.documentIds === null || scope.documentIds.length === 0))
      || (externalProcessing && !externalConfirmed)
      || (codexProcessing && (!classification || !domain.generation_execution_preview.disclosure_version))
    ) return;

    if (externalProcessing) setExternalConfirmed(false);
    setClassification("");
    requestController.current?.abort();
    const controller = new AbortController();
    requestController.current = controller;
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    setSearching(true);
    setPendingQuery(normalized);
    setQuery("");
    setError("");
    setRetryQuery("");
    try {
      const active = await ensureSession();
      if (requestGeneration.current !== generation || controller.signal.aborted) return;
      const request: TurnRequest = pendingRequest.current?.sessionId === active.id && pendingRequest.current.request.query === normalized
        ? pendingRequest.current.request : {
        connection_version_id: domain.connection_version.id,
        query: normalized,
        workspace_ids: scope.workspaceIds,
        folder_ids: scope.folderIds,
        ...(scope.documentIds !== null ? { document_ids: scope.documentIds } : {}),
        top_k: 10,
        include_diagnostics: true,
        request_id: crypto.randomUUID(), expected_revision: active.revision,
        ...(codexProcessing && classification ? { codex_input_approval: {
          classification, consented: true, disclosure_version: domain.generation_execution_preview.disclosure_version,
        } } : {}),
      };
      pendingRequest.current = {sessionId: active.id, request};
      const detail = await sendConversationTurn(domain.slug, active.id, request, controller.signal);
      if (requestGeneration.current === generation && !controller.signal.aborted) {
        saveSession(detail); pendingRequest.current = null; setTranscript([]);
      }
    } catch (caught) {
      if (requestGeneration.current === generation && !controller.signal.aborted) {
        const failure = conversationFailure(caught);
        setError(failure.message);
        setRetryQuery(failure.action === "retry" ? normalized : "");
        if (failure.action !== "retry") setQuery(normalized);
        setRequiresDomainReentry(failure.action === "reenter");
        setRequiresScopeRevision(failure.action === "revise-scope");
        setRequiresContextReset(failure.action === "reset-context");
      }
    } finally {
      if (requestGeneration.current === generation) {
        requestController.current = null;
        setPendingQuery("");
        setSearching(false);
      }
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (canSend) void sendQuestion(query);
  }

  function cancelCurrent({ restoreQuery = true }: { restoreQuery?: boolean } = {}) {
    setExternalConfirmed(false); setClassification("");
    requestGeneration.current += 1;
    requestController.current?.abort(); requestController.current = null;
    if (restoreQuery && pendingQuery) setQuery(pendingQuery);
    setPendingQuery(""); setSearching(false);
    const pending = pendingRequest.current;
    const running = sessionRef.current?.turns.find(turn => turn.status === "running");
    const sessionId = pending?.sessionId ?? sessionRef.current?.id;
    const requestId = pending?.request.request_id ?? running?.request_id;
    pendingRequest.current = null;
    if (sessionId && requestId) {
      const generation = requestGeneration.current;
      setSessionLoading(true);
      void cancelConversationTurn(domain.slug, sessionId, requestId).then(detail => {
        if (requestGeneration.current === generation) saveSession(detail);
      }).catch(() => { if (requestGeneration.current === generation) setSessionError("취소 상태를 확인하지 못했습니다. 대화를 다시 열어 확인해 주세요."); })
        .finally(() => { if (requestGeneration.current === generation) setSessionLoading(false); });
    }
  }

  function startNewConversation() {
    requestGeneration.current += 1; requestController.current?.abort(); requestController.current = null;
    pendingRequest.current = null; sessionRef.current = null; creatingSession.current = null;
    setSession(null); setSessionLoading(false); updateUrl(null);
    setTranscript([]); setQuery(""); setPendingQuery(""); setSearching(false); setError(""); setSessionError("");
    setRetryQuery(""); setExternalConfirmed(false); setClassification(""); setSelectedEvidence(null); setSelectedOriginal(null);
    setRequiresContextReset(false); setRequiresScopeRevision(false); setRequiresDomainReentry(false);
    setEditingTitle(null); setConfirmDelete(false); setUploadOpen(false); setPendingFiles([]); setDraggingFiles(false); dragDepth.current = 0; setAttachmentMenuOpen(false);
    updateSelection(initialSelection); setWorkspaceIds(initialSelection ? unique(initialSelection.documents.map(document => document.workspace_id)) : initialWorkspaceIds); setFolderIds([]);
    setKnownDocuments(initialSelection?.documents ?? []);
    setScopeMode(initialSelection ? "documents" : "workspace");
  }

  function handleQuestionKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    const nativeEvent = event.nativeEvent as globalThis.KeyboardEvent;
    if (event.key !== "Enter" || event.shiftKey || event.altKey || event.ctrlKey || event.metaKey) return;
    if (composing.current || nativeEvent.isComposing) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  function openEvidence(evidence: Evidence) {
    returnFocus.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setSelectedEvidence(evidence);
  }

  function closeEvidence() {
    setSelectedEvidence(null);
    queueMicrotask(() => returnFocus.current?.focus());
  }

  function openDocumentPanel() {
    if (searching) return;
    setSelectionReturnFocus(attachmentButtonRef.current);
    setSelectionPanelOpen(true);
  }

  function applyDocuments(documents: DocumentSummary[]) {
    if (!markScopeChange()) return;
    setScopeMode("documents");
    updateSelection(selectionFromDocuments(documents));
    setKnownDocuments(current => [...current.filter(item => !documents.some(document => document.id === item.id)), ...documents]);
    if (documents.length > 0) {
      const documentWorkspaceIds = unique(documents.map(({ workspace_id }) => workspace_id));
      const allowedFolderIds = new Set(documentWorkspaceIds.flatMap((workspaceId) => (foldersByWorkspace[workspaceId] ?? []).map(({ id }) => id)));
      setWorkspaceIds(documentWorkspaceIds);
      setFolderIds((current) => current.filter((id) => allowedFolderIds.has(id)));
    }
  }

  function openSelectedVersion(document: DocumentSummary, versionId: string) {
    originalReturnFocus.current = globalThis.document.activeElement instanceof HTMLElement
      ? globalThis.document.activeElement
      : null;
    setSelectedOriginal({ document, versionId });
  }

  function closeSelectedVersion() {
    setSelectedOriginal(null);
    queueMicrotask(() => originalReturnFocus.current?.focus());
  }

  return (
    <main className="conversation-shell">
      <header className="conversation-header">
        <div>
          <p className="eyebrow">도메인 대화</p>
          <h1>{domain.display_name}</h1>
          <p>{domain.description}</p>
        </div>
        <div className="conversation-header-actions">
          <DomainNavigation slug={domain.slug} displayName={domain.display_name} current="chat" />
          <button
            type="button"
            className="secondary-button"
            disabled={requiresDomainReentry || requiresScopeRevision}
            onClick={startNewConversation}
          >새 대화</button>
          <Link href={routes.workshopRagSearch} onClick={() => cancelCurrent({ restoreQuery: false })}>도메인 변경</Link>
        </div>
      </header>

      <div className="conversation-layout">
      <aside className="conversation-sidebar" aria-label="대화 목록">
        <details open><summary>내 대화</summary>
        {sessions.length === 0 ? <p>저장된 대화가 없습니다.</p> : <ul>{sessions.map(item => <li key={item.id}><button type="button" aria-current={session?.id === item.id ? "page" : undefined} onClick={() => void selectSession(item.id)}>{item.title}</button></li>)}</ul>}
      </details></aside>
      <div className="conversation-main" onDragEnter={event => {
        if (!event.dataTransfer.types.includes("Files")) return;
        event.preventDefault(); dragDepth.current += 1; setDraggingFiles(true);
      }} onDragOver={event => {
        if (!event.dataTransfer.types.includes("Files")) return;
        event.preventDefault(); event.dataTransfer.dropEffect = searching || attachmentBusy || sessionLoading || requiresDomainReentry ? "none" : "copy";
      }} onDragLeave={event => {
        if (!event.dataTransfer.types.includes("Files")) return;
        event.preventDefault(); dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (!dragDepth.current) setDraggingFiles(false);
      }} onDrop={event => {
        if (!event.dataTransfer.types.includes("Files")) return;
        event.preventDefault(); dragDepth.current = 0; setDraggingFiles(false);
        receiveFiles(Array.from(event.dataTransfer.files));
      }}>
      {draggingFiles ? <div className="conversation-drop-overlay" role="status"><strong>{searching || attachmentBusy || sessionLoading || requiresDomainReentry ? "현재 작업이 끝난 뒤 첨부하세요" : "파일을 놓아 대화에 첨부"}</strong><span>허용된 개인 공간에 저장합니다</span></div> : null}
      {sessionError ? <p role="alert">{sessionError}</p> : null}
      {sessionLoading ? <p role="status">대화를 불러오는 중…</p> : null}
      {session ? <div className="conversation-session-heading"><h2>{session.title}</h2>
        <button type="button" aria-label="대화 이름 변경" disabled={searching} onClick={() => setEditingTitle(session.title)}>이름 변경</button>
        <button type="button" aria-label="대화 삭제" onClick={() => setConfirmDelete(true)}>삭제</button>
        {editingTitle !== null ? <div><label>대화 제목<input value={editingTitle} maxLength={180} onChange={event => setEditingTitle(event.target.value)} /></label><button type="button" disabled={!editingTitle.trim()} onClick={() => void editTitle()}>제목 저장</button><button type="button" onClick={() => setEditingTitle(null)}>취소</button></div> : null}
        {confirmDelete ? <div role="alert"><p>이 대화를 삭제할까요?</p><button type="button" onClick={() => void removeSession()}>삭제 확인</button><button type="button" onClick={() => setConfirmDelete(false)}>유지</button></div> : null}
      </div> : null}
      <details className="conversation-processing"><summary>모델 및 처리 안내</summary><ProcessingDisclosure domain={domain} /></details>

      {!domain.ready || !domain.connection_version ? (
        <section className="conversation-unavailable" role="alert">
          <h2>이 도메인은 아직 대화할 수 없습니다</h2>
          <p>{readinessMessage(domain.readiness.reason_codes)}</p>
          <Link href={routes.workshopRagSearch}>다른 도메인 선택</Link>
        </section>
      ) : null}

      <div
        className="conversation-transcript"
        aria-label="현재 대화"
        ref={transcriptRef}
        onScroll={() => {
          const element = transcriptRef.current;
          if (!element) return;
          stickToBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 80;
        }}
      >

        {transcript.length === 0 && !session?.turns.length && !pendingQuery ? (
          <section className="conversation-welcome"><h2>무엇을 확인할까요?</h2><p>답변의 인용을 열어 원문과 일치 여부를 확인할 수 있습니다.</p></section>
        ) : null}
        {session?.turns.map((turn, index) => <div key={turn.id}>
          {index > 0 && session.turns[index - 1].segment !== turn.segment ? <div className="scope-divider" role="separator">검색 범위·문맥 변경</div> : null}
          {turn.redacted || !turn.request_scope ? <article className="conversation-turn"><p role="status">현재 권한으로 이 대화 내용을 표시할 수 없습니다.</p></article>
            : turn.response ? <ConversationAnswer turn={{type: "answer", query: turn.query, result: turn.response, scope: {
              workspaceIds: turn.request_scope.workspace_ids,
              workspaceNames: domain.workspace_options.filter(item => turn.request_scope?.workspace_ids.includes(item.id)).map(item => item.name),
              folderIds: turn.request_scope.folder_ids ?? [], folderNames: Object.values(foldersByWorkspace).flat().filter(folder => turn.request_scope?.folder_ids?.includes(folder.id)).map(folder => folder.name), documentIds: turn.request_scope.document_ids ?? null,
              documentNames: knownDocuments.filter(item => turn.request_scope?.document_ids?.includes(item.id)).map(item => item.name), documents: knownDocuments,
            }}} onOpenEvidence={openEvidence} onOpenSelectedVersion={openSelectedVersion} />
            : <article className="conversation-turn"><p className="user-message"><strong>나</strong>{turn.query}</p><p role="status">{turn.status === "cancelled" ? (turn.execution_terminated ? "답변 생성을 취소했습니다." : "취소를 요청했습니다. 실행 종료 확인 중입니다.") : turn.status === "interrupted" ? "답변 생성이 중단되었습니다. 새 질문으로 다시 요청할 수 있습니다." : turn.status === "running" ? "답변 생성 중입니다. 상태를 새로고침해 확인할 수 있습니다." : conversationFailure(new ApiError("", 500, turn.error_code ?? "generation_failed")).message}</p>
              {turn.status === "running" ? <><button type="button" onClick={() => cancelCurrent()}>답변 취소</button><button type="button" onClick={() => void selectSession(session.id)}>상태 새로고침</button></> : null}
              {turn.status === "cancelled" && !turn.execution_terminated ? <button type="button" onClick={() => void selectSession(session.id)}>상태 새로고침</button> : null}
            </article>}
        </div>)}
        {transcript.map((item) => item.type === "scope-divider" ? (
          <div className="scope-divider" role="separator" key={`divider-${item.key}`}><span>검색 범위 변경</span></div>
        ) : (
          <ConversationAnswer key={`${item.result.generation.turn_id ?? item.query}`} turn={item} onOpenEvidence={openEvidence} onOpenSelectedVersion={openSelectedVersion} />
        ))}
        {pendingQuery ? (
          <article className="conversation-turn is-pending" aria-label={`${pendingQuery} 답변 생성 중`}>
            <p className="user-message"><strong>나</strong>{pendingQuery}</p>
            <p role="status">근거를 검색하고 답변을 검증하는 중…</p>
          </article>
        ) : null}
        <div ref={transcriptEndRef} />
      </div>

      <form className="conversation-composer" onSubmit={handleSubmit}>
      <ScopeSelector
        key={`${scopeMode}:${scopeOpen ? `open:${workspaceIds.join(",")}:${folderIds.join(",")}` : "closed"}`}
        domain={domain}
        workspaceIds={workspaceIds}
        folderIds={folderIds}
        foldersByWorkspace={foldersByWorkspace}
        open={scopeOpen}
        searching={searching || requiresDomainReentry}
        folderError={folderError}
        mode={scopeMode}
        selection={selection}
        onApplyScope={applyScope}
        onToggleOpen={() => setScopeOpen((current) => !current)}
      />


        <div className="conversation-file-chips" aria-label="선택한 문서">{selection?.documentIds.map((id, index) => <span key={id}>{selection.documentNames[index] ?? "선택 문서"}<button type="button" disabled={searching} aria-label={`${selection.documentNames[index] ?? "선택 문서" } 제외`} onClick={() => {
          if (!markScopeChange()) return;
          updateSelection({...selection, documentIds: selection.documentIds.filter(value => value !== id), documentNames: selection.documentNames.filter((_, candidate) => candidate !== index), documents: selection.documents.filter(document => document.id !== id)});
        }}>×</button></span>)}</div>
        {uploadOpen ? <ConversationAttachments slug={domain.slug} sessionId={session?.id ?? null} ensureSession={ensureSession} pendingFiles={pendingFiles} onFilesConsumed={() => setPendingFiles([])} onBusy={setAttachmentBusy} onSelect={documents => applyDocuments([...(selectionRef.current?.documents ?? []).filter(item => !documents.some(document => document.id === item.id)), ...documents])} /> : null}
        {error ? (
          <div className="conversation-error" role="alert">
            <p>{error}</p>
            {requiresDomainReentry ? (
              <Link href={routes.workshopRagSearch}>도메인 선택으로 돌아가기</Link>
            ) : requiresContextReset ? (
              <button type="button" onClick={markScopeChange}>변경된 범위로 새 문맥 시작</button>
            ) : retryQuery ? (
              <button
                type="button"
                disabled={(externalProcessing && !externalConfirmed) || (codexProcessing && !classification)}
                onClick={() => void sendQuestion(retryQuery)}
              >같은 질문 다시 시도</button>
            ) : null}
          </div>
        ) : null}
        {codexProcessing ? <CodexQuestionConsent classification={classification} consented={externalConfirmed} disabled={searching || requiresDomainReentry} onClassification={setClassification} onConsent={setExternalConfirmed} /> : null}
        {externalProcessing && !codexProcessing ? (
          <label className="external-question-confirmation">
            <input
              type="checkbox"
              aria-label="이번 질문의 외부 처리를 확인했습니다"
              checked={externalConfirmed}
              disabled={searching || requiresDomainReentry}
              onChange={(event) => setExternalConfirmed(event.target.checked)}
            />
            이번 질문의 외부 처리를 확인했습니다
            <small>관리자가 저장한 전송 승인과 별개로, 매 질문 전에 전송 범위를 확인하는 절차입니다.</small>
          </label>
        ) : null}
        <label className="conversation-question">
          <span className="visually-hidden">질문</span>
          <textarea
            ref={questionRef}
            rows={1}
            value={query}
            disabled={searching || !domain.ready || requiresDomainReentry}
            onChange={(event) => { setQuery(event.target.value); if (codexProcessing) setExternalConfirmed(false); }}
            onKeyDown={handleQuestionKeyDown}
            onCompositionStart={() => { composing.current = true; }}
            onCompositionEnd={() => { composing.current = false; }}
            placeholder="질문을 입력하세요"
          />
        </label>
        <div className="composer-actions">
          <input ref={fileInputRef} type="file" multiple hidden aria-label="대화에 파일 첨부" onChange={event => { receiveFiles(Array.from(event.target.files ?? [])); event.target.value = ""; }} />
          <div ref={menuRef} className="conversation-add-menu">
            <button ref={attachmentButtonRef} type="button" aria-label="문서 추가" aria-expanded={attachmentMenuOpen} disabled={searching || sessionLoading} onClick={() => setAttachmentMenuOpen(current => !current)}>＋</button>
            {attachmentMenuOpen ? <div role="group" aria-label="문서 추가 방법"><button type="button" onClick={() => {openDocumentPanel(); setAttachmentMenuOpen(false);}}>기존 문서 선택</button><button type="button" disabled={attachmentBusy} onClick={() => {fileInputRef.current?.click(); setAttachmentMenuOpen(false);}}>PC 파일 첨부</button><small>파일을 대화창에 끌어다 놓으세요</small></div> : null}
          </div>
          <button type="submit" aria-label="질문 보내기" disabled={!canSend}>↑</button>
          {searching ? <button type="button" className="secondary-button" onClick={() => cancelCurrent()}>답변 취소</button> : null}
          <span>Enter 전송 · Shift+Enter 줄바꿈</span>
        </div>
      </form>

      </div></div>
      {selectedEvidence ? <EvidencePanel evidence={selectedEvidence} onClose={closeEvidence} /> : null}
      {selectionPanelOpen ? <DocumentSelectionPanel slug={domain.slug} currentDocuments={selection?.documents ?? []} workspaceIds={workspaceIds} folderIds={folderIds} foldersByWorkspace={foldersByWorkspace} onApply={applyDocuments} onClose={() => setSelectionPanelOpen(false)} returnFocus={selectionReturnFocus} onSelectionInvalidated={() => {
        setRequiresScopeRevision(true);
        updateSelection(null);
        setExternalConfirmed(false);
        setClassification("");
        setRetryQuery("");
        setError("선택 문서의 위치, 권한 또는 활성 버전이 변경되었습니다. 문서를 다시 선택하거나 범위를 다시 설정해 주세요.");
      }} /> : null}
      {selectedOriginal ? <div className="conversation-original-panel"><LibraryViewer key={`${selectedOriginal.document.workspace_id}:${selectedOriginal.document.id}:${selectedOriginal.versionId}`} document={selectedOriginal.document} initialVersionId={selectedOriginal.versionId} showEvidenceApproval={false} onClose={closeSelectedVersion} onVersionChange={() => undefined} /></div> : null}
    </main>
  );
}

function readinessMessage(reasonCodes: string[]): string {
  if (reasonCodes.includes("generation_not_configured")) return "생성형 답변 구성이 아직 준비되지 않았습니다.";
  if (reasonCodes.includes("configuration_not_evaluated")) return "평가를 통과한 RAG 구성이 필요합니다.";
  if (reasonCodes.some((code) => code.includes("index") || code.includes("search"))) return "검색 색인을 준비하고 있습니다.";
  return "관리자가 검색과 생성 연결을 준비하고 있습니다.";
}

type ConversationFailureAction = "retry" | "revise-scope" | "reset-context" | "reenter" | "stop";

interface ConversationFailure {
  message: string;
  action: ConversationFailureAction;
}

function conversationFailure(caught: unknown): ConversationFailure {
  if (caught instanceof ApiError) {
    const messages: Record<string, string> = {
      domain_inactive: "도메인 연결이 비활성화되었습니다. 최신 상태를 확인하려면 도메인을 다시 선택해 주세요.",
      domain_connection_changed: "도메인 연결이 변경되었습니다. 최신 연결과 검색 범위를 다시 불러오려면 도메인을 다시 선택해 주세요.",
      domain_not_ready: "검색 또는 생성 서비스가 아직 준비되지 않았습니다. 도메인을 다시 선택해 최신 상태를 확인해 주세요.",
      configuration_not_evaluated: "평가를 통과한 구성이 필요합니다. 도메인을 다시 선택해 최신 상태를 확인해 주세요.",
      generation_not_configured: "생성형 답변 구성이 준비되지 않았습니다. 도메인을 다시 선택해 최신 상태를 확인해 주세요.",
      search_scope_empty: "검색할 지식 공간을 하나 이상 선택해 주세요.",
      deployment_not_allowed_in_environment: "현재 환경에서는 선택한 생성 실행을 사용할 수 없습니다.",
      workspace_external_transfer_denied: "연결된 RAG 구성의 지식 공간 전송 정책이 외부 생성을 허용하지 않습니다. 관리자 확인 후 도메인을 다시 선택해 주세요.",
      provider_not_allowed: "현재 데이터 정책이 선택한 외부 생성 서비스를 허용하지 않습니다.",
      deployment_not_ready: "선택한 생성 실행이 준비되지 않았습니다.",
      provider_authentication_failed: "생성 서비스 인증 상태를 확인할 수 없습니다.",
      provider_rate_limited: "생성 서비스 요청 한도에 도달했습니다.",
      provider_timeout: "생성 서비스 응답 시간이 초과되었습니다.",
      provider_invalid_response: "생성 서비스가 유효한 응답을 반환하지 않았습니다.",
      structured_output_invalid: "생성 서비스의 구조화 응답을 검증할 수 없습니다.",
      citation_validation_failed: "생성 답변의 근거 인용을 검증하지 못했습니다.",
      conversation_scope_changed: "문서 버전 또는 선택 범위가 변경되었습니다. 현재 범위로 새 문맥을 시작해 주세요.",
      selected_documents_not_ready: "선택한 문서 중 검색 준비가 끝나지 않은 문서가 있습니다. 선택을 수정해 주세요.",
    };
    const reentryCodes = new Set([
      "domain_inactive",
      "domain_connection_changed",
      "domain_not_ready",
      "configuration_not_evaluated",
      "generation_not_configured",
      "deployment_not_allowed_in_environment",
      "workspace_external_transfer_denied",
      "provider_not_allowed",
      "provider_authentication_failed",
    ]);
    const scopeRevisionCodes = new Set([
      "search_scope_empty",
      "selected_documents_not_ready",
    ]);
    return {
      message: `${messages[caught.code] ?? "답변을 만들지 못했습니다. 잠시 후 다시 시도해 주세요."} (${caught.code}${caught.correlationId ? ` · 참조: ${caught.correlationId}` : ""})`,
      action: reentryCodes.has(caught.code)
        ? "reenter"
        : caught.code === "conversation_scope_changed"
        ? "reset-context"
        : scopeRevisionCodes.has(caught.code)
        ? "revise-scope"
        : caught.status < 500
        ? "stop"
        : "retry",
    };
  }
  return {
    message: "답변을 만들지 못했습니다. 네트워크 상태를 확인하고 다시 시도해 주세요.",
    action: "retry",
  };
}

function unique(values: string[]): string[] {
  return [...new Set(values)];
}
