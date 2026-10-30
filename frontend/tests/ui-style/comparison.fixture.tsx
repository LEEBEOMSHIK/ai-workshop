import { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import type { ComparisonDetail } from "../../src/features/rag/comparisons/api";
import { ComparisonReportView } from "../../src/features/rag/comparisons/ComparisonReportView";
import styles from "../../src/features/rag/comparisons/Comparisons.module.css";
import "../../src/app/styles.css";

function Preview() {
  const [detail, setDetail] = useState<ComparisonDetail | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void fetch("/comparison-data.json", { signal: controller.signal })
      .then(response => response.json()).then(setDetail);
    return () => controller.abort();
  }, []);
  return <main className={styles.page}>
    <p>공개 합성 자료 · 실제 컴포넌트 반응형 검증 · 모델 호출 없음</p>
    {detail ? <ComparisonReportView detail={detail} /> : <p>화면 준비 중</p>}
  </main>;
}

createRoot(document.getElementById("root")!).render(<Preview />);
