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
import {
  type DomainSearchRequest,
  type Evidence,
  type Folder,
  listConversationFolders,
  searchDomain,
} from "./api";
import { ConversationAnswer } from "./ConversationAnswer";
import { EvidencePanel } from "./EvidencePanel";
import { ProcessingDisclosure } from "./ProcessingDisclosure";
import { CodexQuestionConsent } from "./CodexQuestionConsent";
import { DocumentSelectionPanel } from "./DocumentSelectionPanel";
import { buildScopeSnapshot, ScopeSelector } from "./ScopeSelector";
import { selectionFromDocuments, type ScopeMode, type ScopeSnapshot, type Selection, type TranscriptItem } from "./types";

const MAX_HISTORY_ITEMS = 20;

export function ConversationPage({ domain, initialSelection = null, initialWorkspaceIds = [] }: { domain: Domain; initialSelection?: Selection; initialWorkspaceIds?: string[] }) {
  const preview = domain.generation_execution_preview;
  const sessionKey = JSON.stringify([domain.id, domain.connection_version?.id, preview, domain.workspace_options, initialSelection?.documentIds, initialWorkspaceIds]);
  return <ConversationSession key={sessionKey} domain={domain} initialSelection={initialSelection} initialWorkspaceIds={initialWorkspaceIds} />;
}

function ConversationSession({ domain, initialSelection, initialWorkspaceIds }: { domain: Domain; initialSelection: Selection; initialWorkspaceIds: string[] }) {
  const [selection, setSelection] = useState<Selection>(initialSelection);
  const [scopeMode, setScopeMode] = useState<ScopeMode>(initialSelection === null ? "workspace" : "documents");
  const [workspaceIds, setWorkspaceIds] = useState(() => initialSelection === null
    ? domain.workspace_options.filter(({ id }) => initialWorkspaceIds.includes(id)).map(({ id }) => id)
    : unique(initialSelection.documents.map(({ workspace_id }) => workspace_id)));
  const [folderIds, setFolderIds] = useState<string[]>([]);
  const [foldersByWorkspace, setFoldersByWorkspace] = useState<Record<string, Folder[]>>({});
  const [scopeOpen, setScopeOpen] = useState(false);
  const [query, setQuery] = useState("");
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
  const [selectionReturnFocus, setSelectionReturnFocus] = useState<HTMLElement | null>(null);
  const originalReturnFocus = useRef<HTMLElement | null>(null);

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
    && !requiresDomainReentry
    && !requiresScopeRevision
    && !requiresContextReset
    && !selectionPanelOpen
    && (!externalProcessing || externalConfirmed)
    && (!codexProcessing || (classification !== "" && !!domain.generation_execution_preview?.disclosure_version));

  function markScopeChange(): boolean {
    if (searching) return false;
    setExternalConfirmed(false);
    setClassification("");
    setError("");
    setRetryQuery("");
    setRequiresScopeRevision(false);
    setRequiresContextReset(false);
    setTranscript((current) => {
      if (!current.some((item) => item.type === "answer") || current.at(-1)?.type === "scope-divider") {
        return current;
      }
      return [...current, { type: "scope-divider", key: Date.now() }];
    });
    return true;
  }

  function applyScope(mode: Exclude<ScopeMode, "documents">, nextWorkspaceIds: string[], nextFolderIds: string[]) {
    if (!markScopeChange()) return;
    setScopeMode(mode); setSelection(null); setWorkspaceIds(nextWorkspaceIds); setFolderIds(nextFolderIds); setScopeOpen(false);
  }

  function currentScope(): ScopeSnapshot {
    return buildScopeSnapshot(domain, workspaceIds, folderIds, foldersByWorkspace, selection);
  }

  function segmentHistory(): DomainSearchRequest["history"] {
    let lastDivider = -1;
    for (let index = transcript.length - 1; index >= 0; index -= 1) {
      if (transcript[index].type === "scope-divider") {
        lastDivider = index;
        break;
      }
    }
    return transcript.slice(lastDivider + 1).flatMap((item) => {
      if (item.type !== "answer") return [];
      if (
        item.result.generation.status !== "answered"
        || !item.result.generation.text
        || !item.result.generation.turn_id
        || !item.result.generation.validation_token
      ) return [];
      const turns: NonNullable<DomainSearchRequest["history"]> = [
        { role: "user", content: item.query, turn_id: null, validation_token: null },
        {
          role: "assistant",
          content: item.result.generation.text,
          turn_id: item.result.generation.turn_id,
          validation_token: item.result.generation.validation_token,
        },
      ];
      return turns;
    }).slice(-MAX_HISTORY_ITEMS);
  }

  async function sendQuestion(question: string) {
    const normalized = question.trim();
    const scope = currentScope();
    if (
      normalized.length < 2
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
    const history = segmentHistory();
    setSearching(true);
    setPendingQuery(normalized);
    setQuery("");
    setError("");
    setRetryQuery("");
    try {
      const result = await searchDomain(domain.slug, {
        connection_version_id: domain.connection_version.id,
        query: normalized,
        workspace_ids: scope.workspaceIds,
        folder_ids: scope.folderIds,
        ...(scope.documentIds !== null ? { document_ids: scope.documentIds } : {}),
        top_k: 10,
        history,
        ...(codexProcessing && classification ? { codex_input_approval: {
          classification, consented: true, disclosure_version: domain.generation_execution_preview.disclosure_version,
        } } : {}),
      }, controller.signal);
      if (requestGeneration.current === generation && !controller.signal.aborted) {
        setTranscript((current) => [...current, { type: "answer", query: normalized, result, scope }]);
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
    requestController.current?.abort();
    requestController.current = null;
    if (restoreQuery && pendingQuery) setQuery(pendingQuery);
    setPendingQuery("");
    setSearching(false);
  }

  function startNewConversation() {
    if (requiresDomainReentry || requiresScopeRevision) return;
    cancelCurrent({ restoreQuery: false });
    setTranscript([]);
    setQuery("");
    setError("");
    setRetryQuery("");
    setExternalConfirmed(false);
    setSelectedEvidence(null);
    setRequiresContextReset(false);
    setRequiresScopeRevision(false);
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

  function openDocumentPanel(opener: HTMLButtonElement) {
    if (searching) return;
    setSelectionReturnFocus(opener);
    setSelectionPanelOpen(true);
  }

  function applyDocuments(documents: DocumentSummary[]) {
    if (!markScopeChange()) return;
    setScopeMode("documents");
    setSelection(selectionFromDocuments(documents));
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
        onOpenDocuments={openDocumentPanel}
        onApplyScope={applyScope}
        onToggleOpen={() => setScopeOpen((current) => !current)}
      />

      <ProcessingDisclosure domain={domain} />

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
        <p className="conversation-notice">현재 대화는 이 브라우저 화면에서만 유지되며 새로고침하면 초기화됩니다.</p>
        {transcript.length === 0 && !pendingQuery ? (
          <section className="conversation-welcome"><h2>무엇을 확인할까요?</h2><p>답변의 인용을 열어 원문과 일치 여부를 확인할 수 있습니다.</p></section>
        ) : null}
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
        <label>
          질문
          <textarea
            rows={3}
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
          <button type="submit" disabled={!canSend}>질문 보내기</button>
          {searching ? <button type="button" className="secondary-button" onClick={() => cancelCurrent()}>답변 취소</button> : null}
          <span>Enter 전송 · Shift+Enter 줄바꿈</span>
        </div>
      </form>

      {selectedEvidence ? <EvidencePanel evidence={selectedEvidence} onClose={closeEvidence} /> : null}
      {selectionPanelOpen ? <DocumentSelectionPanel slug={domain.slug} currentDocuments={selection?.documents ?? []} workspaceIds={workspaceIds} folderIds={folderIds} foldersByWorkspace={foldersByWorkspace} onApply={applyDocuments} onClose={() => setSelectionPanelOpen(false)} returnFocus={selectionReturnFocus} onSelectionInvalidated={() => {
        setRequiresScopeRevision(true);
        setSelection(null);
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
