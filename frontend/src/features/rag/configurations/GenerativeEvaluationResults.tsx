import { useEffect, useRef, useState, type ReactNode } from "react";
import type { GenerativeRun } from "./generative-api";
import styles from "./GenerativeEvaluation.module.css";

export type EvaluationResultView = "answer" | "evidence" | "review";
type Attempt = GenerativeRun["attempts"][number];
const filters = ["전체", "실패", "근거 부족", "검토 필요", "진행 중"] as const;
type Filter = typeof filters[number];
function latestAttempts(attempts: Attempt[]) {
  const latest = new Map<string, Attempt>();
  for (const item of attempts) {
    const key = JSON.stringify([item.configuration_version_id, item.repetition]);
    if (!latest.has(key) || latest.get(key)!.attempt_number < item.attempt_number) latest.set(key, item);
  }
  return [...latest.values()];
}
function matches(item: Attempt, filter: Filter) {
  if (filter === "실패") return ["failed", "interrupted"].includes(item.status) || item.metrics?.correctness === "failed" || item.metrics?.citation_valid === false;
  if (filter === "근거 부족") return item.observation?.generation_status === "insufficient_evidence";
  if (filter === "검토 필요") return item.status === "completed" && (!item.metrics || item.metrics.correctness === "unreviewed");
  if (filter === "진행 중") return ["pending", "running"].includes(item.status);
  return true;
}

export function GenerativeEvaluationResults({ run, caseId, onSelect, renderAttempt }: {
  run: GenerativeRun; caseId: string; onSelect: (id: string) => void; renderAttempt: (item: Attempt, view: EvaluationResultView) => ReactNode;
}) {
  const tabRefs = useRef<Partial<Record<EvaluationResultView, HTMLButtonElement | null>>>({});
  const [view, setView] = useState<EvaluationResultView>("answer");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("전체");
  const [repetition, setRepetition] = useState(0);
  const [mobileDetail, setMobileDetail] = useState(Boolean(caseId));
  const [historyOpen, setHistoryOpen] = useState(false);
  const cases = [...new Map(run.attempts.map(item => [item.case_id, item.query])).entries()];
  const filteredCases = cases.filter(([id, query]) => query.toLocaleLowerCase().includes(search.toLocaleLowerCase()) && latestAttempts(run.attempts.filter(item => item.case_id === id)).some(item => matches(item, filter)));
  const hasFilter = Boolean(search) || filter !== "전체";
  const selectedId = hasFilter && !filteredCases.some(([id]) => id === caseId) ? filteredCases[0]?.[0] ?? "" : caseId || cases[0]?.[0] || "";
  useEffect(() => { if (selectedId !== caseId) onSelect(selectedId); }, [caseId, selectedId, onSelect]);
  const all = run.attempts.filter(item => item.case_id === selectedId);
  const latest = latestAttempts(all);
  const repetitions = [...new Set(latest.map(item => item.repetition))].sort((a, b) => a - b);
  const activeRepetition = repetitions.includes(repetition) ? repetition : repetitions[0];
  const displayed = latest.filter(item => item.repetition === activeRepetition);
  const history = all.filter(item => item.repetition === activeRepetition && !displayed.some(current => current.id === item.id));
  function visibleCases(term: string, status: Filter) {
    return cases.filter(([id, query]) => query.toLocaleLowerCase().includes(term.toLocaleLowerCase()) && latestAttempts(run.attempts.filter(item => item.case_id === id)).some(item => matches(item, status)));
  }
  const visible = filteredCases;
  const page = Math.floor(Math.max(0, visible.findIndex(([id]) => id === selectedId)) / 5);
  const pageCount = Math.ceil(visible.length / 5);
  const pageCases = visible.slice(page * 5, page * 5 + 5);
  function filterQuestions(term: string, status: Filter) {
    setSearch(term); setFilter(status);
    const next = visibleCases(term, status);
    if (!next.some(([id]) => id === selectedId)) { onSelect(next[0]?.[0] ?? ""); setRepetition(0); setHistoryOpen(false); }
  }
  function select(id: string) { onSelect(id); setRepetition(0); setHistoryOpen(false); setMobileDetail(true); }
  return <div className={styles.results} data-mobile-detail={mobileDetail}>
    <aside className={styles.questionList} aria-label="평가 질문 목록">
      <label>질문 검색<input value={search} onChange={event => filterQuestions(event.target.value, filter)} /></label>
      <label className={styles.compactSelect}>질문 상태<select value={filter} onChange={event => filterQuestions(search, event.target.value as Filter)}>{filters.map(value => <option key={value} value={value}>{value}</option>)}</select></label>
      <p>질문 {visible.length} / {cases.length}개</p>
      <ul>{pageCases.map(([id, query]) => {
        const items = latestAttempts(run.attempts.filter(item => item.case_id === id));
        const labels = filters.slice(1).filter(value => items.some(item => matches(item, value)));
        return <li key={id}><button type="button" aria-pressed={selectedId === id} onClick={() => select(id)}><strong title={query}>{query}</strong><span>{labels.join(" · ") || "검토 결과 확인"}</span></button></li>;
      })}</ul>
      {pageCount > 1 ? <nav className={styles.pagination} aria-label="질문 페이지"><button type="button" aria-label="이전 질문 페이지" disabled={page === 0} onClick={() => { onSelect(visible[(page - 1) * 5][0]); setRepetition(0); setHistoryOpen(false); }}>이전</button><span>{page + 1} / {pageCount} 페이지</span><button type="button" aria-label="다음 질문 페이지" disabled={page + 1 === pageCount} onClick={() => { onSelect(visible[(page + 1) * 5][0]); setRepetition(0); setHistoryOpen(false); }}>다음</button></nav> : null}
      {!visible.length ? <p>검색 조건에 맞는 질문이 없습니다.</p> : null}
    </aside>
    <section className={styles.questionDetail} aria-label="선택 질문 비교">
      <button type="button" className={styles.backToList} onClick={() => setMobileDetail(false)}>질문 목록으로</button>
      {!visible.length ? <p>표시할 질문이 없습니다. 검색어나 상태 필터를 변경하세요.</p> : !all.length ? <p role="alert">연결된 사례를 찾을 수 없습니다.</p> : <>
        <p className={styles.selectedQuestion}>{all[0].query}</p>
        <p className={styles.caseSummary}>최신 시도 {latest.filter(item => item.status === "completed").length}/{latest.length}회 완료 · 정답 통과 {latest.filter(item => item.metrics?.correctness === "passed").length}회</p>
        <div className={styles.detailToolbar}><label className={styles.compactSelect}>반복<select value={activeRepetition} onChange={event => { setRepetition(Number(event.target.value)); setHistoryOpen(false); }}>{repetitions.map(value => <option key={value} value={value}>{value + 1}회차</option>)}</select></label>
        <div className={styles.contentTabs} role="tablist" aria-label="비교 내용">{([["answer", "답변 비교"], ["evidence", "근거·진단"], ["review", "검토"]] as const).map(([id, label]) => <button type="button" role="tab" ref={node => { tabRefs.current[id] = node; }} tabIndex={view === id ? 0 : -1} onKeyDown={event => {
          const order: EvaluationResultView[] = ["answer", "evidence", "review"];
          const index = order.indexOf(id);
          const next = event.key === "ArrowRight" ? (index + 1) % order.length : event.key === "ArrowLeft" ? (index + order.length - 1) % order.length : event.key === "Home" ? 0 : event.key === "End" ? order.length - 1 : null;
          if (next == null) return;
          event.preventDefault(); setView(order[next]); tabRefs.current[order[next]]?.focus();
        }} aria-selected={view === id} aria-controls={`evaluation-${run.id}-content`} id={`evaluation-${run.id}-${id}`} key={id} onClick={() => setView(id)}>{label}</button>)}</div></div>
        {view === "evidence" ? <p>검색·문맥 충족률은 정답 근거 포함 비율이며 유사도가 아닙니다. 실행 완료와 정답 판정은 별개입니다.</p> : null}
        <div role="tabpanel" id={`evaluation-${run.id}-content`} aria-labelledby={`evaluation-${run.id}-${view}`} className={styles.comparison}>{displayed.map(item => renderAttempt(item, view))}</div>
        {history.length ? <details open={historyOpen} onToggle={event => setHistoryOpen(event.currentTarget.open)}><summary>이 반복의 이전 시도 {history.length}건</summary>{historyOpen ? <div className={styles.comparison}>{history.map(item => renderAttempt(item, view))}</div> : null}</details> : null}
      </>}
    </section>
  </div>;
}
