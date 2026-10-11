import Link from "next/link";
import type { FlowDefinition } from "./types";
import { FlowReader } from "./FlowReader";
import styles from "./Flowcharts.module.css";

export function FlowchartsPage({ flows, selectedFlow, flowHref }: {
  flows: readonly FlowDefinition[];
  selectedFlow: FlowDefinition;
  flowHref: (categoryId: string, flowId: string) => string;
}) {
  const categories = [...new Map(flows.map(flow => [flow.categoryId, flow.categoryLabel])).entries()];
  const categoryFlows = flows.filter(flow => flow.categoryId === selectedFlow.categoryId);
  return <main className={styles.shell}>
    <header className={styles.header}><p className={styles.eyebrow}>FLOW GUIDE</p><h1>흐름도</h1>
      <p>기술별 처리 과정과 조건을 확인하세요. 실제 실행 상태는 대화의 검색 진단과 실행 모니터링에서 확인합니다.</p>
    </header>
    <div className={styles.layout}>
      <div className={styles.selector}>
        <nav className={styles.categories} aria-label="기술 선택">
          {categories.map(([id, label]) => {
            const active = id === selectedFlow.categoryId;
            const target = active ? selectedFlow : flows.find(flow => flow.categoryId === id)!;
            return <Link key={id} href={flowHref(id, target.id)} aria-current={active ? "true" : undefined}>{label}</Link>;
          })}
        </nav>
        <nav className={styles.flowChoices} aria-label="흐름 선택">
          {categoryFlows.map(flow => <Link key={flow.id} href={flowHref(flow.categoryId, flow.id)} aria-current={flow.id === selectedFlow.id ? "page" : undefined}>{flow.title}</Link>)}
        </nav>
      </div>
      <FlowReader key={`${selectedFlow.categoryId}/${selectedFlow.id}`} flow={selectedFlow} />
    </div>
  </main>;
}
