import { useEffect, useState, type ReactNode } from "react";
import type { GenerativeRun } from "./generative-api";
import styles from "./GenerativeEvaluation.module.css";

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
  run: GenerativeRun; caseId: string; onSelect: (id: string) => void; renderAttempt: (item: Attempt) => ReactNode;
}) {
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
  function filterQuestions(term: string, status: Filter) {
    setSearch(term); setFilter(status);
    const next = visibleCases(term, status);
    if (!next.some(([id]) => id === selectedId)) { onSelect(next[0]?.[0] ?? ""); setRepetition(0); setHistoryOpen(false); }
  }
  function select(id: string) { onSelect(id); setRepetition(0); setHistoryOpen(false); setMobileDetail(true); }
  return <div className={styles.results} data-mobile-detail={mobileDetail}>
    <aside className={styles.questionList} aria-label="평가 질문 목록">
      <label>질문 검색<input value={search} onChange={event => filterQuestions(event.target.value, filter)} /></label>
      <div className={styles.filters} aria-label="질문 상태 필터">{filters.map(value => <button key={value} type="button" aria-pressed={filter === value} onClick={() => filterQuestions(search, value)}>{value}</button>)}</div>
      <p>질문 {visible.length} / {cases.length}개 · 실행 완료와 정답 판정은 별개입니다.</p>
      <ul>{visible.map(([id, query]) => {
        const items = latestAttempts(run.attempts.filter(item => item.case_id === id));
        const labels = filters.slice(1).filter(value => items.some(item => matches(item, value)));
        return <li key={id}><button type="button" aria-pressed={selectedId === id} onClick={() => select(id)}><strong>{query}</strong><span>{labels.join(" · ") || "검토 결과 확인"}</span><span>실행 완료 {items.filter(item => item.status === "completed").length}/{items.length}회 · 정답 통과 {items.filter(item => item.metrics?.correctness === "passed").length}회</span></button></li>;
      })}</ul>
      {!visible.length ? <p>검색 조건에 맞는 질문이 없습니다.</p> : null}
    </aside>
    <section className={styles.questionDetail} aria-label="선택 질문 비교">
      <button type="button" className={styles.backToList} onClick={() => setMobileDetail(false)}>질문 목록으로</button>
      {!visible.length ? <p>표시할 질문이 없습니다. 검색어나 상태 필터를 변경하세요.</p> : !all.length ? <p role="alert">연결된 사례를 찾을 수 없습니다.</p> : <>
        <p className={styles.selectedQuestion}>{all[0].query}</p>
        <p>같은 질문·반복의 최신 시도를 구성별로 비교합니다. 검색·문맥 충족률은 정답 근거 포함 비율이며 유사도가 아닙니다.</p>
        <div className={styles.badges} aria-label="반복 선택">{repetitions.map(value => <button type="button" key={value} aria-pressed={activeRepetition === value} onClick={() => { setRepetition(value); setHistoryOpen(false); }}>반복 {value + 1}</button>)}</div>
        <div className={styles.comparison}>{displayed.map(renderAttempt)}</div>
        {history.length ? <details open={historyOpen} onToggle={event => setHistoryOpen(event.currentTarget.open)}><summary>이 반복의 이전 시도 {history.length}건</summary>{historyOpen ? <div className={styles.comparison}>{history.map(renderAttempt)}</div> : null}</details> : null}
      </>}
    </section>
  </div>;
}
