"use client";

import { useEffect, useRef, useState } from "react";

import {
  EvidenceApprovalRequest,
  type EvidenceApprovalContext,
  type EvidenceApprovalRequestCreate,
  listEvidenceApprovalRequests,
  requestEvidenceApproval,
  listLibraryDocumentVersions,
  loadPdfPage,
  originalDownloadPath,
  previewOriginal,
  type AssetVersion,
  type DocumentSummary,
  type OriginalPreview,
} from "./api";
import { ApiError } from "../../shared/api/client";
import styles from "./DocumentLibrary.module.css";

const versionStatus: Record<AssetVersion["status"], string> = {
  stored: "저장됨",
  processing: "처리 중",
  ready: "원본 준비됨",
  failed: "실패",
};

interface LibraryViewerProps {
  document: DocumentSummary;
  initialVersionId: string | null;
  onClose: () => void;
  onVersionChange: (versionId: string) => void;
}

export function LibraryViewer({ document, initialVersionId, onClose, onVersionChange }: LibraryViewerProps) {
  const [selectedVersionId, setSelectedVersionId] = useState(initialVersionId ?? document.active_version_id);
  const [versions, setVersions] = useState<AssetVersion[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [versionError, setVersionError] = useState("");
  const [versionRetry, setVersionRetry] = useState(0);
  const [loadingMoreVersions, setLoadingMoreVersions] = useState(false);
  const [preview, setPreview] = useState<OriginalPreview | null>(null);
  const [loading, setLoading] = useState(Boolean(selectedVersionId));
  const [error, setError] = useState(selectedVersionId ? "" : "열람할 수 있는 활성 원본 버전이 없습니다.");
  const [retry, setRetry] = useState(0);
  const [wrap, setWrap] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [page, setPage] = useState(1);
  const [pageUrl, setPageUrl] = useState<string | null>(null);
  const [pageError, setPageError] = useState("");
  const [pageRetry, setPageRetry] = useState(0);
  const pageLoadKeyRef = useRef<string | null>(null);
  const versionCursorRequests = useRef(new Set<string>());
  const closeButtonRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    closeButtonRef.current?.focus();
  }, []);

  useEffect(() => {
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopImmediatePropagation();
      onClose();
    };
    window.addEventListener("keydown", closeOnEscape, true);
    return () => window.removeEventListener("keydown", closeOnEscape, true);
  }, [onClose]);

  useEffect(() => {
    const controller = new AbortController();
    void listLibraryDocumentVersions(document.workspace_id, document.id, null, controller.signal)
      .then((result) => {
        setVersions(result.items);
        setNextCursor(result.next_cursor);
      })
      .catch((failure: unknown) => {
        if (!isAbort(failure)) setVersionError("버전 목록을 불러오지 못했습니다.");
      });
    return () => controller.abort();
  }, [document.id, document.workspace_id, versionRetry]);

  useEffect(() => {
    if (!selectedVersionId) return;
    const controller = new AbortController();
    void previewOriginal(document.id, selectedVersionId, controller.signal)
      .then((result) => setPreview(result))
      .catch((failure: unknown) => {
        if (!isAbort(failure)) setError("원문을 불러오지 못했습니다. 권한 또는 원본 상태를 확인해 주세요.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [document.id, retry, selectedVersionId]);

  useEffect(() => {
    if (preview?.kind !== "pdf" || !selectedVersionId) return;
    const pageKey = `${selectedVersionId}:${page}:${pageRetry}`;
    if (pageLoadKeyRef.current === pageKey) return;
    pageLoadKeyRef.current = pageKey;
    let objectUrl: string | null = null;
    void loadPdfPage(document.id, selectedVersionId, page)
      .then((blob) => {
        if (pageLoadKeyRef.current !== pageKey) return;
        objectUrl = URL.createObjectURL(blob);
        setPageUrl(objectUrl);
      })
      .catch((failure: unknown) => {
        if (pageLoadKeyRef.current !== pageKey || isAbort(failure)) return;
        setPageError("PDF 페이지를 불러오지 못했습니다.");
      });
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [document.id, page, pageRetry, preview?.kind, selectedVersionId]);

  async function loadMoreVersions() {
    const cursor = nextCursor;
    if (!cursor || versionCursorRequests.current.has(cursor)) return;
    versionCursorRequests.current.add(cursor);
    setLoadingMoreVersions(true);
    try {
      const result = await listLibraryDocumentVersions(document.workspace_id, document.id, cursor);
      setVersions((current) => mergeVersions(current, result.items));
      setNextCursor((current) => current === cursor ? result.next_cursor : current);
    } catch {
      setVersionError("다음 버전 목록을 불러오지 못했습니다.");
    } finally {
      versionCursorRequests.current.delete(cursor);
      setLoadingMoreVersions(false);
    }
  }

  function chooseVersion(version: AssetVersion) {
    if (version.status !== "ready") return;
    setLoading(true);
    setPreview(null);
    setError("");
    setPage(1);
    setPageUrl(null);
    setPageError("");
    setSelectedVersionId(version.id);
    onVersionChange(version.id);
  }

  function changePage(nextPage: number) {
    setPageUrl(null);
    setPageError("");
    setPage(nextPage);
  }

  function retryPreview() {
    setLoading(Boolean(selectedVersionId));
    setPreview(null);
    setError(selectedVersionId ? "" : "열람할 수 있는 활성 원본 버전이 없습니다.");
    setRetry((value) => value + 1);
  }

  const exactVersion = versions.find((version) => version.id === selectedVersionId) ?? null;

  return <aside className={`${styles.viewer} ${expanded ? styles.viewerExpanded : ""}`} aria-label={`${document.name} 원문`}>
    <header className={styles.viewerHeader}>
      <div>
        <p className={styles.kicker}>독립 원문 열람</p>
        <h2>{document.name} 원문</h2>
        <p>{selectedVersionId ? selectedVersionLabel(document, selectedVersionId, preview?.version) : "활성 원본 없음"}</p>
      </div>
      <div className={styles.viewerActions}>
        <button type="button" onClick={() => setExpanded((current) => !current)}>{expanded ? "기본 크기" : "넓게 보기"}</button>
        <button ref={closeButtonRef} type="button" onClick={onClose}>문서 닫기</button>
      </div>
    </header>

    <DocumentInformation document={document} selectedVersionId={selectedVersionId} exactVersion={exactVersion} preview={preview} loading={loading} />

    <div className={styles.viewerBody} aria-busy={loading}>
      {loading ? <p role="status">원문을 불러오는 중…</p> : null}
      {error ? <div role="alert"><p>{error}</p><button type="button" onClick={retryPreview}>다시 시도</button></div> : null}
      {!loading && !error && preview ? <PreviewBody preview={preview} page={page} pageUrl={pageUrl} pageError={pageError} wrap={wrap} onPage={changePage} onPageRetry={() => { setPageError(""); setPageRetry((value) => value + 1); }} onWrap={() => setWrap((current) => !current)} /> : null}
    </div>

    {selectedVersionId ? <a className={styles.download} href={originalDownloadPath(document.id, selectedVersionId)}>원본 내려받기</a> : null}
    <VersionEvidenceApproval key={JSON.stringify([document.workspace_id, document.id, selectedVersionId])} selectedVersionId={selectedVersionId} />
    <section className={styles.versions} aria-label="문서 버전">
      <h3>버전</h3>
      {versionError ? <div role="alert"><p>{versionError}</p><button type="button" onClick={() => { setVersionError(""); setVersionRetry((value) => value + 1); }}>버전 목록 다시 시도</button></div> : null}
      {versions.map((version) => <button type="button" disabled={version.status !== "ready"} aria-pressed={selectedVersionId === version.id} key={version.id} onClick={() => chooseVersion(version)}>
        {versionLabel(document, version)}
      </button>)}
      {nextCursor ? <button type="button" disabled={loadingMoreVersions} onClick={loadMoreVersions}>버전 더 보기</button> : null}
    </section>
  </aside>;
}

function VersionEvidenceApproval({ selectedVersionId }: { selectedVersionId: string | null }) {
  const [approvalRequests, setApprovalRequests] = useState<EvidenceApprovalRequest[]>([]);
  const [approvalContext, setApprovalContext] = useState<EvidenceApprovalContext | null>(null);
  const [approvalLoading, setApprovalLoading] = useState(Boolean(selectedVersionId));
  const [approvalError, setApprovalError] = useState("");
  const [requesting, setRequesting] = useState(false);
  const [requestMessage, setRequestMessage] = useState("");
  const approvalSequence = useRef(0);

  useEffect(() => {
    const sequence = ++approvalSequence.current;
    if (!selectedVersionId) return;
    const controller = new AbortController();
    void listEvidenceApprovalRequests(selectedVersionId, controller.signal)
      .then((page) => {
        if (controller.signal.aborted || sequence !== approvalSequence.current) return;
        setApprovalRequests(Array.isArray(page?.items) ? page.items : []);
        setApprovalContext(page?.context ?? null);
      })
      .catch((failure: unknown) => {
        if (!controller.signal.aborted && !isAbort(failure) && sequence === approvalSequence.current) {
          setApprovalRequests([]);
          setApprovalContext(null);
          setApprovalError(apiErrorMessage(failure));
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && sequence === approvalSequence.current) setApprovalLoading(false);
      });
    return () => {
      controller.abort();
      approvalSequence.current = -1;
    };
  }, [selectedVersionId]);

  async function requestApproval() {
    if (!selectedVersionId || requestApprovalDisabled) return;
    const payload: EvidenceApprovalRequestCreate = {
      request_id: crypto.randomUUID(),
      revision_id: selectedVersionId,
      provider: "development_codex_exec",
      expected_approval_generation: approvalContext?.approval_generation ?? 0,
    };
    setRequesting(true);
    setApprovalError("");
    setRequestMessage("");
    const sequence = ++approvalSequence.current;
    try {
      await requestEvidenceApproval(selectedVersionId, payload);
      if (sequence !== approvalSequence.current) return;
      const page = await listEvidenceApprovalRequests(selectedVersionId);
      if (sequence !== approvalSequence.current) return;
      setApprovalRequests(page.items);
      setApprovalContext(page.context);
      setRequestMessage("요청이 접수되었습니다. 관리자 승인 대기 중입니다.");
    } catch (failure: unknown) {
      if (sequence !== approvalSequence.current) return;
      setApprovalError(apiErrorMessage(failure));
    } finally {
      if (sequence === approvalSequence.current) setRequesting(false);
    }
  }

  const hasPendingRequest = approvalRequests.some((item) => item.status === "pending");
  const isGloballyApproved = approvalContext?.approval_status === "approved";
  const requestApprovalDisabled = Boolean(!selectedVersionId || requesting || approvalLoading || hasPendingRequest || isGloballyApproved);
  const requestStatus = !selectedVersionId
    ? "승인 요청할 원본 버전이 없습니다."
    : approvalLoading
      ? ""
      : isGloballyApproved
        ? `이 버전은 현재 승인 상태입니다. (세대 ${approvalContext?.approval_generation ?? 0})`
        : approvalRequests.length === 0
          ? "요청 내역이 없습니다. 아래에서 Codex 자료 검토 요청을 보낼 수 있습니다."
          : "";

  return <section className={styles.evidenceApproval} aria-label="Codex 전송 승인">
    <h3>Codex 전송 승인</h3>
    <p>문서 버전별 승인 요청은 공개·합성 처리 상태를 확인하기 위한 문서 분류 검토 절차입니다.</p>
    <p>{requestStatus}</p>
    {approvalLoading ? <p role="status">승인 요청 상태를 불러오는 중…</p> : null}
    {approvalError ? <p role="status">{approvalError}</p> : null}
    {requestMessage ? <p role="status">{requestMessage}</p> : null}
    {approvalRequests.length > 0 ? <ul className={styles.evidenceList}>
      {approvalRequests.map((item) => <li key={item.id}>
        <p>요청 {formatEvidenceStatus(item.status)} · 상태변경 {item.state_revision}</p>
        <p>요청 시각 {formatRequestTime(item.created_at)} · 처리 {item.resolved_at ? formatRequestTime(item.resolved_at) : "미처리"}</p>
        <p>요청 ID {item.id}</p>
      </li>)}
    </ul> : !approvalLoading && !approvalError ? <p>요청 내역이 없습니다.</p> : null}
    <button type="button" disabled={requestApprovalDisabled} onClick={() => void requestApproval()}>
      {requesting ? "요청 처리 중…" : "이 버전에 대한 Codex 승인 요청"}
    </button>
  </section>;
}

function apiErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return "로그인 상태를 확인해 주세요.";
  if (error instanceof ApiError && error.status === 403) return "문서 승인 요청 권한이 없어 조회할 수 없습니다.";
  if (error instanceof ApiError && error.status === 409) return "승인 상태가 변경되어 요청을 다시 가져옵니다. 잠시 뒤 다시 시도해 주세요.";
  if (error instanceof ApiError) return `요청 처리 중 오류가 발생했습니다. (${error.code})`;
  return "요청 처리 중 임시 오류가 발생했습니다.";
}

function formatRequestTime(value: string): string {
  const timestamp = new Date(value);
  return Number.isNaN(timestamp.getTime()) ? value : timestamp.toLocaleString("ko-KR");
}

function formatEvidenceStatus(status: EvidenceApprovalRequest["status"]): string {
  if (status === "approved") return "승인됨";
  if (status === "rejected") return "반려됨";
  return "요청 중";
}

function DocumentInformation({ document, selectedVersionId, exactVersion, preview, loading }: {
  document: DocumentSummary;
  selectedVersionId: string | null;
  exactVersion: AssetVersion | null;
  preview: OriginalPreview | null;
  loading: boolean;
}) {
  const name = preview?.name ?? (selectedVersionId ? loading ? "파일 이름 확인 중" : "파일 이름 정보 없음" : document.name);
  const size = preview?.size ?? exactVersion?.size;
  const mediaType = exactVersion?.media_type ?? (selectedVersionId ? "상세 형식 정보 없음" : "형식 정보 없음");
  const previewKind = preview ? previewKindLabels[preview.kind] : selectedVersionId ? loading ? "확인 중" : "미리보기 정보 없음" : "미리보기 없음";
  const state = exactVersion ? versionStatus[exactVersion.status] : preview ? "원본 준비됨" : selectedVersionId ? loading ? "확인 중" : "원본 상태 정보 없음" : "활성 원본 없음";
  return <section className={styles.documentInfo} aria-label="문서 정보">
    <h3>문서 정보</h3>
    <dl>
      <div><dt>파일 이름</dt><dd>{name}</dd></div>
      <div><dt>크기</dt><dd>{size === undefined ? "크기 정보 없음" : `${size.toLocaleString("ko-KR")} B`}</dd></div>
      <div><dt>파일 형식</dt><dd>{mediaType}</dd></div>
      <div><dt>미리보기</dt><dd>{previewKind}</dd></div>
      <div><dt>원본 상태</dt><dd>{state}</dd></div>
    </dl>
  </section>;
}

function PreviewBody({ preview, page, pageUrl, pageError, wrap, onPage, onPageRetry, onWrap }: {
  preview: OriginalPreview;
  page: number;
  pageUrl: string | null;
  pageError: string;
  wrap: boolean;
  onPage: (page: number) => void;
  onPageRetry: () => void;
  onWrap: () => void;
}) {
  if (preview.kind === "text" || preview.kind === "markdown") return <div className={styles.textPreview}>
    <button type="button" onClick={onWrap}>{wrap ? "줄 바꿈 끄기" : "줄 바꿈 켜기"}</button>
    <pre className={wrap ? styles.wrap : ""}>{preview.text}</pre>
  </div>;
  if (preview.kind === "unsupported") return <div className={styles.unsupported}>
    <p>이 형식은 아직 미리보기를 지원하지 않습니다.</p>
    <p>원본은 외부 서비스로 전송되지 않으며, 아래의 명시적인 내려받기 링크로만 받을 수 있습니다.</p>
  </div>;
  const pageCount = preview.page_count ?? 0;
  return <div className={styles.pdfPreview}>
    <div className={styles.pageControls}>
      <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)}>이전 페이지</button>
      <span>{page} / {pageCount}</span>
      <button type="button" disabled={page >= pageCount} onClick={() => onPage(page + 1)}>다음 페이지</button>
    </div>
    {pageError ? <div role="alert"><p>{pageError}</p><button type="button" onClick={onPageRetry}>PDF 페이지 다시 시도</button></div> : null}
    {!pageError && !pageUrl ? <p role="status">PDF 페이지를 불러오는 중…</p> : null}
    {/* Authenticated request-scoped blob URLs cannot use the Next image optimizer. */}
    {/* eslint-disable-next-line @next/next/no-img-element */}
    {pageUrl ? <img src={pageUrl} alt={`${preview.name} ${page}쪽`} /> : null}
  </div>;
}

function versionLabel(document: DocumentSummary, version: AssetVersion): string {
  const flags: string[] = [];
  if (version.id === document.active_version_id) flags.push("활성 원본");
  if (version.id === document.latest_version_id) flags.push("최신");
  if (version.id !== document.active_version_id || version.status !== "ready") flags.push(versionStatus[version.status]);
  return `버전 ${version.number}${flags.length ? ` · ${flags.join(" · ")}` : ""}`;
}

function selectedVersionLabel(document: DocumentSummary, versionId: string, number?: number): string {
  const suffix = versionId === document.active_version_id ? " · 활성 원본" : " · 선택한 과거 원본";
  return number ? `버전 ${number}${suffix}` : "선택한 원본을 확인하는 중";
}

const previewKindLabels: Record<OriginalPreview["kind"], string> = {
  markdown: "Markdown",
  pdf: "PDF",
  text: "텍스트",
  unsupported: "지원하지 않음",
};

function mergeVersions(existing: AssetVersion[], additions: AssetVersion[]): AssetVersion[] {
  const ids = new Set(existing.map((version) => version.id));
  return [...existing, ...additions.filter((version) => !ids.has(version.id))];
}

function isAbort(failure: unknown): boolean {
  return failure instanceof DOMException && failure.name === "AbortError";
}
