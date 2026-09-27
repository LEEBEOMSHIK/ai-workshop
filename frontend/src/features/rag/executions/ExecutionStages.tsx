import type { Stage } from "./api";
import styles from "./ExecutionMonitoring.module.css";

export const stageLabels: Record<Stage["stage"], string> = {
  request: "요청·권한 확인", history: "이전 대화 준비", contextualization: "질문 문맥화",
  retrieval: "검색", selection: "근거 선택", generation: "답변 생성",
  citation_validation: "인용 검증", persistence: "결과 저장",
};
const stateLabels = { pending: "대기", running: "진행", completed: "완료", failed: "실패", skipped: "생략", unrecorded: "미기록" };
export function duration(value: number | null | undefined) {
  return value == null ? "시간 미기록" : `${(value / 1000).toFixed(2)}초`;
}
export function ExecutionStages({ stages }: { stages: Stage[] }) {
  return <ol className={styles.stages} aria-label="RAG 처리 단계">
    {stages.map(stage => <li key={stage.stage} data-state={stage.state}>
      <strong>{stageLabels[stage.stage]}</strong><span>{stateLabels[stage.state]}</span>
      <small>{duration(stage.duration_ms)}</small>{stage.reason ? <code>{stage.reason}</code> : null}
    </li>)}
  </ol>;
}
