"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { routes } from "../../../shared/routing/routes";
import { Button } from "../../../shared/ui/Button";
import { getComparisonReport, type ComparisonDetail } from "./api";
import { ComparisonReportView } from "./ComparisonReportView";
import styles from "./Comparisons.module.css";

export function ComparisonDetailPage({ id }: { id: string }) {
  return <ComparisonDetailContent key={id} id={id} />;
}

function ComparisonDetailContent({ id }: { id: string }) {
  const [detail, setDetail] = useState<ComparisonDetail | null>(null);
  const [error, setError] = useState("");
  const [refreshCount, setRefreshCount] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    getComparisonReport(id, controller.signal).then(value => {
      if (controller.signal.aborted) return;
      if (value.id !== id || value.record_kind !== "imported_comparison") throw new Error("comparison_identity_mismatch");
      setDetail(value); setError("");
    }).catch(() => {
      if (!controller.signal.aborted) { setDetail(null); setError("비교 기록을 열 수 없습니다. 로그인과 현재 원문 접근 권한을 확인해 주세요."); }
    });
    return () => controller.abort();
  }, [id, refreshCount]);
  function refresh() { setDetail(null); setError(""); setRefreshCount(value => value + 1); }
  return <main className={styles.page}>
    <nav className={styles.toolbar} aria-label="비교 기록 탐색">
      <div className={styles.links}>
        <Link className={styles.navigationLink} href={routes.adminRagComparisons}>← 저장된 모델 비교</Link>
        <Link className={styles.navigationLink} href={`${routes.adminRagConfigurations}?tab=comparison&view=stored`}>평가 화면</Link>
        <Link className={styles.navigationLink} href={routes.adminRagExecutions}>실행 목록</Link>
      </div>
      <Button onClick={refresh} disabled={!detail && !error}>비교 기록 새로고침</Button>
    </nav>
    {!detail && !error ? <p role="status">저장된 비교 결과를 확인하고 있습니다…</p> : null}
    {error ? <p role="alert">{error}</p> : null}
    {detail ? <ComparisonReportView detail={detail} /> : null}
  </main>;
}
