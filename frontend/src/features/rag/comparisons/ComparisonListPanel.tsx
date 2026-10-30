"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { comparisonPath } from "../../../shared/routing/routes";
import { Button } from "../../../shared/ui/Button";
import { listComparisonReports, type ComparisonDetail, type ComparisonSummary } from "./api";
import { ComparisonImportForm } from "./ComparisonImportForm";
import { billingLabels } from "./ComparisonReportView";
import { formatComparisonMoney } from "./comparison-format";
import styles from "./Comparisons.module.css";

export function ComparisonListPanel() {
  const [items, setItems] = useState<ComparisonSummary[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(true);
  const [refreshCount, setRefreshCount] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    listComparisonReports(controller.signal).then(value => {
      if (!controller.signal.aborted) { setItems(value.items); setBusy(false); setError(""); }
    }).catch(() => {
      if (!controller.signal.aborted) { setItems([]); setBusy(false); setError("비교 기록을 불러오지 못했습니다. 로그인과 현재 원문 접근 권한을 확인해 주세요."); }
    });
    return () => controller.abort();
  }, [refreshCount]);
  function refresh() { setItems([]); setBusy(true); setError(""); setRefreshCount(value => value + 1); }
  function imported(detail: ComparisonDetail) {
    const report = detail.report;
    const summary: ComparisonSummary = { id: detail.id, record_kind: detail.record_kind, created_at: detail.created_at,
      source_key: report.source_key, title: report.title, question: report.question, completed_at: report.completed_at,
      unique_question_count: report.unique_question_count, request_count: report.requests.length,
      models: [...new Set(report.requests.map(request => request.model))], estimated_total_usd: report.estimated_total_usd, billing_status: report.billing_status };
    setItems(current => [summary, ...current.filter(item => item.id !== summary.id)]);
  }
  return <section className={styles.panelContent} aria-labelledby="stored-comparisons-title">
    <header className={styles.toolbar}><div><h2 id="stored-comparisons-title">저장된 모델 비교</h2><p className={styles.muted}>완료된 비교 결과와 원문 검토를 함께 확인합니다. 일반 실행 통계나 평가 승격에는 합산하지 않습니다.</p></div>
      <Button onClick={refresh} disabled={busy}>비교 목록 새로고침</Button>
    </header>
    {error ? <p role="alert">{error}</p> : null}
    {busy ? <p role="status">저장된 비교 목록을 불러오고 있습니다…</p> : null}
    {!busy && !error ? <div className={styles.reportList}>{items.map(item => <article className={styles.reportItem} key={item.id}>
      <p className={styles.eyebrow}>가져온 완료 기록 · <time dateTime={item.completed_at}>{new Date(item.completed_at).toLocaleString("ko-KR")}</time></p>
      <h3><Link className={styles.navigationLink} href={comparisonPath(item.id)}>{item.title}</Link></h3><p>{item.question}</p>
      <p className={styles.muted}>{item.models.join(" · ")} · 고유 질문 {item.unique_question_count}개 · 완료 요청 {item.request_count}회</p>
      <p className={styles.muted}>예상 API 비용 {item.billing_status === "not_applicable" ? "해당 없음" : formatComparisonMoney(item.estimated_total_usd)} · {billingLabels[item.billing_status]}</p>
    </article>)}{!items.length ? <p>저장된 모델 비교가 없습니다.</p> : null}</div> : null}
    {!error && !busy ? <ComparisonImportForm key={refreshCount} onImported={imported} /> : null}
  </section>;
}
