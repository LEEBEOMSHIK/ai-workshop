"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { routes, ragDomainChatPath } from "../../../shared/routing/routes";
import { EvidencePanel } from "../conversation/EvidencePanel";
import { CodexModelIdentity } from "../conversation/CodexModelIdentity";
import type { Evidence } from "../conversation/api";
import { buildSourceHref } from "../search/source-route-query";
import { getExecutionDetail, type ExecutionDetail } from "./api";
import { ExecutionStages, duration } from "./ExecutionStages";
import { answerLabels, executionLabels } from "./ExecutionListPage";
import styles from "./ExecutionMonitoring.module.css";

const score = (value: number | null | undefined) => value == null ? "미기록" : value.toFixed(4);
const reasons: Record<string, string> = { selected: "선택", budget_exceeded: "입력 예산 초과", below_threshold: "기준 점수 미달", conflict_context_budget_exceeded: "상충 근거 예산 초과" };

export function ExecutionDetailPage({ id, kind = "execution" }: { id: string; kind?: "execution" | "legacy" }) {
  const [detail, setDetail] = useState<ExecutionDetail | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const closeEvidence = useCallback(() => setEvidence(null), []);
  useEffect(() => {
    const controller = new AbortController();
    getExecutionDetail(id, kind, controller.signal).then(value => {
      if (!controller.signal.aborted) { setDetail(value); setError(""); }
    }).catch(() => { if (!controller.signal.aborted) { setDetail(null); setError("실행을 열 수 없습니다. 삭제되었거나 현재 원문 접근 권한이 없을 수 있습니다."); } });
    return () => controller.abort();
  }, [id, kind, attempt]);
  const selection = detail?.stages.find(stage => stage.selection)?.selection;
  return <main className={styles.page}>
    <Link href={routes.adminRagExecutions}>← 실행 목록</Link>
    {error ? <p role="alert">{error} <button onClick={() => setAttempt(value => value + 1)}>다시 시도</button></p> : null}
    {!detail && !error ? <p role="status">실행 상세를 불러오고 있습니다…</p> : null}
    {detail ? <>
      <header><p className={styles.eyebrow}>질문별 실행 상세</p><h1>{detail.query}</h1><p>{new Date(detail.created_at).toLocaleString("ko-KR")} · {duration(detail.duration_ms)}</p>
        <div className={styles.badges}><span>실행: {executionLabels[detail.status]}</span><span>답변: {answerLabels[detail.answer_status ?? ""] ?? "미기록"}</span><span>품질: {detail.quality_status === "unreviewed" ? "미검증" : detail.quality_status === "passed" ? "통과" : "실패"}</span></div>
        {detail.error_code ? <p role="alert">실패 코드: <code>{detail.error_code}</code></p> : null}
        {detail.record_kind === "legacy" ? <p>이전 기록 · 상세 단계 미기록</p> : !detail.observation_complete ? <p>일부 관측 기록이 누락되었습니다.</p> : null}
        {detail.conversation_id && detail.domain_slug ? <Link href={`${ragDomainChatPath(detail.domain_slug)}?conversation=${detail.conversation_id}`}>기존 대화 열기</Link> : null}
      </header>
      <section className={styles.card}><h2>생성 답변</h2>
        <p className={styles.answer}>{detail.generation?.text ?? (detail.answer_status === "insufficient_evidence" ? "답변할 근거가 부족합니다." : "저장된 생성 답변이 없습니다.")}</p>
        {detail.generation?.reason_codes?.map(code => <code key={code}>{code} </code>)}
        {detail.generation?.execution ? <CodexModelIdentity execution={detail.generation.execution} /> : null}
        <h3>답변에 인용된 근거</h3>
        <div className={styles.badges}>{detail.generation?.citations?.flatMap(citation => citation.evidence_ids.map(evidenceId => {
          const item = detail.evidence.find(value => value.source.evidence_unit_id === evidenceId);
          return item ? <button key={`${citation.claim_index}-${evidenceId}`} onClick={() => setEvidence(item)}>[{citation.claim_index + 1}] {item.source.title} · {item.source.location.page ?? "—"}쪽 원문</button> : <span key={`${citation.claim_index}-${evidenceId}`}>인용 원문 연결을 확인할 수 없습니다.</span>;
        }))}</div>
        {!detail.generation?.citations?.length ? <p>저장된 답변 인용이 없습니다.</p> : null}
        <details><summary>생성에 전달된 전체 근거 ({detail.evidence.length})</summary><div className={styles.badges}>{detail.evidence.map(item => <button key={item.source.evidence_unit_id} onClick={() => setEvidence(item)}>{item.source.title} · {item.source.location.page ?? "—"}쪽 원문</button>)}</div></details>
      </section>
      <section><h2>처리 단계</h2><ExecutionStages stages={detail.stages} /></section>
      <details className={styles.card} open><summary>검색 근거·유사도·선택 사유</summary>
        <p className={styles.hint}>반환된 검색 후보의 원점수입니다. 문맥 코사인과 검색 점수는 답변 정확도가 아닙니다.</p>
        {selection ? <><p>전체 {selection.candidate_count}개 · 기록 {selection.candidates?.length ?? 0}개{selection.truncated ? " · 기록 상한으로 일부 생략" : ""}</p><div className={styles.cards}>
          <p>문맥 코사인 기준 {score(selection.min_semantic_score)} · 키워드 충족률 기준 {score(selection.min_keyword_coverage)}</p>
          {selection.candidates?.map(item => <article className={styles.candidate} key={item.chunk_id ?? item.evidence_unit_id}>
            <strong>{reasons[item.reason] ?? item.reason}</strong> · {item.page ?? "—"}쪽
            <dl><dt>문맥 코사인</dt><dd>{score(item.semantic_score)}</dd><dt>키워드 충족률</dt><dd>{score(item.keyword_coverage)}</dd><dt>BM25 점수 / 순위</dt><dd>{score(item.sparse_score)} / {item.sparse_rank ?? "—"}</dd><dt>Dense 점수 / 순위</dt><dd>{score(item.dense_score)} / {item.dense_rank ?? "—"}</dd><dt>RRF 점수 / 순위</dt><dd>{score(item.fused_score)} / {item.fused_rank ?? "—"}</dd></dl>
            <Link href={buildSourceHref(item.asset_version_id, item.projection_id, [], item.page)}>이 후보의 원문 열기</Link>
            <small className={styles.identifier}>문서 {item.document_id} · 버전 {item.asset_version_id}</small>
          </article>)}
        </div></> : <p>이 실행에는 검색 후보 기록이 없습니다.</p>}
      </details>
      <details className={styles.card}><summary>입력 예산·실행 구성</summary>
        {selection ? <dl><dt>그룹 / 근거 단위 / 문자 제한</dt><dd>{selection.group_limit ?? "미기록"} / {selection.unit_limit ?? "미기록"} / {selection.character_limit ?? "미기록"}</dd><dt>전달 근거 단위</dt><dd>{selection.selected_count}</dd><dt>근거 JSON 크기</dt><dd>{selection.serialized_bytes ?? "미기록"} bytes (토큰 수 아님)</dd><dt>구성 버전</dt><dd>{selection.configuration_version_id}</dd><dt>색인 프로파일</dt><dd>{selection.indexing_profile_id}</dd><dt>검색 프로파일</dt><dd>{selection.retrieval_profile_id}</dd><dt>생성 프로파일</dt><dd>{selection.generation_profile_id}</dd><dt>답변 정책 버전</dt><dd>{selection.answer_policy_version_id}</dd></dl> : <p>상세 구성 기록이 없습니다.</p>}
        {detail.usage?.map((usage, index) => <p key={index}>{usage.requested_model} · 공급자 보고 입력 {usage.input_tokens ?? "미보고"} / 출력 {usage.output_tokens ?? "미보고"} 토큰 · {usage.status}</p>)}
      </details>
      <details className={styles.card}><summary>품질 평가</summary><p>정답표 또는 검토 결과가 연결되어야 정답 여부를 판단할 수 있습니다.</p>{detail.evaluation_run_id && detail.evaluation_case_id ? <Link href={`${routes.adminRagConfigurations}?tab=comparison&run=${detail.evaluation_run_id}&case=${detail.evaluation_case_id}`}>연결된 평가 사례</Link> : <p>연결된 생성형 평가가 없습니다.</p>}</details>
    </> : null}
    {evidence ? <EvidencePanel evidence={evidence} onClose={closeEvidence} /> : null}
  </main>;
}
