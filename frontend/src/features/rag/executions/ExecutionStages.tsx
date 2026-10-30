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
  const longest = Math.max(0, ...stages.map(stage => stage.duration_ms ?? 0));
  return <div className={styles.stageContainer}><ol className={styles.stages} aria-label="RAG 처리 단계">
    {stages.map((stage, index) => <li key={stage.stage} data-state={stage.state}>
      <div className={styles.stageHeading}><span className={styles.stageNumber} aria-hidden="true">{index + 1}</span><strong>{stageLabels[stage.stage]}</strong></div>
      <div className={styles.stageValues}><span>{stateLabels[stage.state]}</span><small>{duration(stage.duration_ms)}</small></div>
      {stage.duration_ms == null ? <div className={styles.stageMissing} aria-hidden="true" />
        : <div className={styles.stageMeter} role="meter" aria-label={`${stageLabels[stage.stage]} 소요 시간`}
          aria-valuemin={0} aria-valuemax={longest || 1} aria-valuenow={stage.duration_ms}
          aria-valuetext={duration(stage.duration_ms)}>
          <span style={{ width: `${longest ? stage.duration_ms / longest * 100 : 0}%` }} />
        </div>}
      {stage.reason ? <code>{stage.reason}</code> : null}
    </li>)}
  </ol></div>;
}
