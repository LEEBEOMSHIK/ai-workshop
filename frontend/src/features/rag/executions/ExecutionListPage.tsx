"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { executionPath } from "../../../shared/routing/routes";
import { searchExecutions, type ExecutionSearchRequest, type ExecutionSearchResponse } from "./api";
import { duration, stageLabels } from "./ExecutionStages";
import styles from "./ExecutionMonitoring.module.css";

export const executionLabels: Record<string, string> = { running: "진행 중", completed: "처리 완료", failed: "실행 실패", cancelled: "취소", interrupted: "중단" };
export const answerLabels: Record<string, string> = { answered: "답변 생성", insufficient_evidence: "근거 부족", not_requested: "생성 미요청", citation_validation_failed: "인용 오류" };

export function ExecutionListPage({ initialFilters = {} }: { initialFilters?: ExecutionSearchRequest }) {
  const [filters, setFilters] = useState<ExecutionSearchRequest>({ ...initialFilters, query: "" });
  const [request, setRequest] = useState<ExecutionSearchRequest>({ ...initialFilters, query: "" });
  const [result, setResult] = useState<ExecutionSearchResponse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  useEffect(() => {
    const controller = new AbortController();
    searchExecutions(request, controller.signal).then(value => {
      if (!controller.signal.aborted) { setResult(value); setBusy(false); setError(""); }
    }).catch(() => { if (!controller.signal.aborted) { setError("실행 기록을 불러오지 못했습니다. 접근 권한과 연결 상태를 확인해 주세요."); setBusy(false); } });
    return () => controller.abort();
  }, [request]);
  function load(value: ExecutionSearchRequest) { setBusy(true); setError(""); setRequest(value); }
  function apply() {
    const safe = new URLSearchParams();
    for (const [key, value] of Object.entries(filters)) if (key !== "query" && key !== "cursor" && value) safe.set(key, String(value));
    window.history.replaceState(null, "", `${window.location.pathname}${safe.size ? `?${safe}` : ""}`);
    load({ ...filters, cursor: null });
  }
  return <main className={styles.page}>
    <header><p className={styles.eyebrow}>RAG 관리</p><h1>실행 모니터링</h1><p>대화와 비교 평가의 질문별 답변, 근거, 실패 단계와 처리 시간을 확인합니다.</p>
      <details className={styles.guide}><summary>사용 방법</summary>
        <ol>
          <li>RAG 대화에서 질문하거나 비교 실험에서 생성형 평가를 실행한 뒤 이곳에서 기록을 조회합니다.</li>
          <li>질문 검색과 상태로 찾습니다. 추가 필터에서 실제 대화·평가, 기간, 실패 단계를 좁힐 수 있습니다.</li>
          <li>목록의 질문을 누르면 답변과 처리 단계가 열립니다. 실패한 단계와 오래 걸린 단계를 확인하세요.</li>
          <li>검색 근거·유사도·선택 사유를 펼쳐 후보가 선택되거나 제외된 이유를 보고 원문을 확인합니다.</li>
        </ol>
        <p>기록은 자동으로 새로고침되지 않습니다. 최신 상태는 목록의 조회 버튼으로 다시 불러오세요.</p>
      </details>
    </header>
    <form className={styles.filters} onSubmit={event => { event.preventDefault(); apply(); }}>
      <label>질문 검색<input value={filters.query ?? ""} onChange={e => setFilters({ ...filters, query: e.target.value })} placeholder="질문 내용으로 찾기" /></label>
      <label>실행 상태<select value={filters.status ?? ""} onChange={e => setFilters({ ...filters, status: e.target.value as ExecutionSearchRequest["status"] || null })}><option value="">전체 상태</option>{Object.entries(executionLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>답변 상태<select value={filters.answer_status ?? ""} onChange={e => setFilters({ ...filters, answer_status: e.target.value || null })}><option value="">전체 답변</option>{Object.entries(answerLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <button type="submit" disabled={busy}>조회</button>
      <details className={styles.advanced}><summary>추가 필터 · 실행 종류·기간·구성·단계</summary><div className={styles.filterGrid}>
        <label>실행 종류<select value={filters.kind ?? ""} onChange={e => setFilters({ ...filters, kind: e.target.value as ExecutionSearchRequest["kind"] || null })}><option value="">전체</option><option value="conversation">실제 대화</option><option value="evaluation">평가</option></select></label>
        <label>실패 단계<select value={filters.failed_stage ?? ""} onChange={e => setFilters({ ...filters, failed_stage: e.target.value as ExecutionSearchRequest["failed_stage"] || null })}><option value="">전체</option>{Object.entries(stageLabels).map(([id, label]) => <option key={id} value={id}>{label}</option>)}</select></label>
        <label>시작일<input type="date" value={filters.started_after?.slice(0, 10) ?? ""} onChange={e => setFilters({ ...filters, started_after: e.target.value ? `${e.target.value}T00:00:00+09:00` : null })} /></label>
        <label>종료일<input type="date" value={filters.started_before?.slice(0, 10) ?? ""} onChange={e => setFilters({ ...filters, started_before: e.target.value ? `${e.target.value}T23:59:59.999+09:00` : null })} /></label>
        <label>도메인 ID<input value={filters.domain_id ?? ""} onChange={e => setFilters({ ...filters, domain_id: e.target.value || null })} /></label>
        <label>구성 버전 ID<input value={filters.configuration_version_id ?? ""} onChange={e => setFilters({ ...filters, configuration_version_id: e.target.value || null })} /></label>
      </div></details>
    </form>
    {error ? <div role="alert">{error} <button onClick={() => load({ ...request })}>다시 시도</button></div> : null}
    {busy ? <p role="status">실행 기록을 확인하고 있습니다…</p> : null}
    {!busy && result ? <>
      <section className={styles.stats} aria-label="필터 전체 통계">
        <div><span>전체 실행</span><strong>{result.total}</strong></div><div><span>실행 실패</span><strong>{result.failed_count}</strong></div><div><span>근거 부족</span><strong>{result.insufficient_count}</strong></div><div><span>시간 중앙값 / p95</span><strong>{duration(result.median_ms)} / {duration(result.p95_ms)}</strong><small>측정 {result.duration_count}건 · 미기록 {result.duration_missing}건</small></div>
      </section>
      <p className={styles.hint}>통계는 현재 접근 가능한 전체 필터 결과 기준입니다. 처리 완료와 답변 생성은 정답 검증을 의미하지 않습니다.</p>
      <section className={styles.executionList} aria-label="질문별 실행 목록">
        {result.items.map(row => <article className={styles.executionRow} key={`${row.record_kind}:${row.id}`}>
          <div className={styles.meta}><time>{new Date(row.created_at).toLocaleString("ko-KR")}</time><span>{row.domain_slug ?? "평가"}</span></div>
          <h2><Link href={executionPath(row.id, row.record_kind)}>{row.query || "질문 내용 없음"}</Link></h2>
          <div className={styles.badges}><span data-state={row.status}>{executionLabels[row.status]}</span><span>{answerLabels[row.answer_status ?? ""] ?? "답변 미기록"}</span><span>품질 미검증</span></div>
          <p>문서 {row.document_count}개 · {duration(row.duration_ms)}{row.failed_stage ? ` · ${stageLabels[row.failed_stage]} 실패` : ""}</p>
          {row.record_kind === "legacy" ? <small>이전 기록 · 상세 단계 미기록</small> : !row.observation_complete ? <small>일부 관측 기록 누락</small> : null}
        </article>)}
        {result.items.length === 0 ? <p>조건에 맞는 실행 기록이 없습니다.</p> : null}
      </section>
      <nav className={styles.pagination} aria-label="실행 목록 페이지">{request.cursor ? <button onClick={() => load({ ...request, cursor: null })}>처음으로</button> : null}{result.next_cursor ? <button onClick={() => load({ ...request, cursor: result.next_cursor })}>다음 실행</button> : null}</nav>
    </> : null}
  </main>;
}
