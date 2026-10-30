"use client";

import Link from "next/link";
import { routes } from "../../../shared/routing/routes";
import { ComparisonListPanel } from "./ComparisonListPanel";
import styles from "./Comparisons.module.css";

export function ComparisonListPage() {
  return <main className={styles.page}>
    <nav className={styles.links} aria-label="평가·실행 탐색">
      <Link className={styles.navigationLink} href={`${routes.adminRagConfigurations}?tab=comparison&view=stored`}>← 평가 화면</Link>
      <Link className={styles.navigationLink} href={routes.adminRagExecutions}>실행 목록</Link>
    </nav>
    <header><p className={styles.eyebrow}>RAG 관리</p><h1>모델 비교 기록</h1><p className={styles.muted}>속도·실제 답변·인용·품질 검토와 사용량·비용을 하나의 기록으로 확인합니다.</p></header>
    <ComparisonListPanel />
  </main>;
}
