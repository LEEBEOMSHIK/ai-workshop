"use client";

import Link from "next/link";
import { useEffect, useId, useState } from "react";
import { getExecutionDetail, type ExecutionDetail } from "../executions/api";
import { ExecutionStages } from "../executions/ExecutionStages";
import { buildSourceHref } from "../search/source-route-query";
import styles from "./EvaluationExecutionDiagnostics.module.css";

const score = (value: number | null | undefined) => value == null ? "미기록" : value.toFixed(4);
const reasons: Record<string, string> = { selected: "선택됨", budget_exceeded: "입력 예산 초과", below_threshold: "기준 점수 미달", conflict_context_budget_exceeded: "상충 근거 예산 초과" };

export function EvaluationExecutionDiagnostics({ executionId }: { executionId: string | null | undefined }) {
  return executionId ? <RecordedDiagnostics key={executionId} executionId={executionId} /> : <p>실행 기록이 연결되면 유사도를 확인할 수 있습니다.</p>;
}

function RecordedDiagnostics({ executionId }: { executionId: string }) {
  const panelId = useId();
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<ExecutionDetail | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    getExecutionDetail(executionId, "execution", controller.signal).then(value => {
      if (!controller.signal.aborted) setDetail(value);
    }).catch(() => { if (!controller.signal.aborted) setError(true); });
    return () => controller.abort();
  }, [executionId, open, retry]);
  const selection = detail?.stages.find(stage => stage.selection)?.selection;
  return <section className={styles.root} aria-label="실행 유사도 진단">
    <button type="button" aria-expanded={open} aria-controls={panelId} onClick={() => {
      setOpen(value => !value); setDetail(null); setError(false);
    }}>{open ? "유사도·근거 선택 닫기" : "유사도·근거 선택 보기"}</button>
    {open ? <div id={panelId} className={styles.body}>
      <p>유사도는 정답률이 아닙니다. 검색·문맥 근거 충족률은 정답표의 필수 근거가 포함된 비율이며, 아래 점수와 구분합니다.</p>
      {error ? <p role="alert">진단 기록을 열 수 없습니다. 로그인과 현재 원문 접근 권한을 확인해 주세요. <button type="button" onClick={() => { setError(false); setDetail(null); setRetry(value => value + 1); }}>진단 다시 불러오기</button></p> : !detail ? <p role="status">저장된 진단 기록을 불러오는 중입니다.</p> : null}
      {detail ? <>
        {!detail.observation_complete ? <p>일부 관측 기록이 누락되었습니다.</p> : null}
        {selection ? <>
          <p>검색 후보 {selection.candidate_count}개 · 기록 {selection.candidates?.length ?? 0}개{selection.truncated ? " · 일부 기록 생략" : ""}</p>
          <p>선택 기준: 문맥 코사인 {score(selection.min_semantic_score)} · 키워드 충족률 {score(selection.min_keyword_coverage)}</p>
          <div className={styles.candidates}>{selection.candidates?.map((item, index) => {
            const title = detail.evidence.find(evidence => evidence.source.asset_version_id === item.asset_version_id)?.source.title;
            return <article className={styles.candidate} key={`${item.chunk_id ?? item.evidence_unit_id}-${index}`}>
              <header><strong>후보 {index + 1} · {title ?? "문서"}{item.page == null ? "" : ` · ${item.page}쪽`}</strong><span data-selected={item.reason === "selected"}>{reasons[item.reason] ?? item.reason}</span></header>
              <dl><div><dt>문맥 코사인</dt><dd>{score(item.semantic_score)}</dd></div><div><dt>키워드 충족률</dt><dd>{score(item.keyword_coverage)}</dd></div><div><dt>Dense 점수 / 순위</dt><dd>{score(item.dense_score)} / {item.dense_rank ?? "—"}</dd></div><div><dt>BM25 점수 / 순위</dt><dd>{score(item.sparse_score)} / {item.sparse_rank ?? "—"}</dd></div><div><dt>RRF 점수 / 순위</dt><dd>{score(item.fused_score)} / {item.fused_rank ?? "—"}</dd></div></dl>
              <Link href={buildSourceHref(item.asset_version_id, item.projection_id, [], item.page)}>후보 {index + 1} 원문 보기</Link>
            </article>;
          })}</div>
        </> : <p>이 실행에는 검색 후보 점수가 기록되지 않았습니다.</p>}
        <details><summary>단계별 시간과 실패 위치</summary><ExecutionStages stages={detail.stages} /></details>
      </> : null}
    </div> : null}
  </section>;
}
