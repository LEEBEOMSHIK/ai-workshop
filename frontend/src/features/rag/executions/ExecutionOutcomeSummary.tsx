import type { ExecutionDetail } from "./api";
import { duration } from "./ExecutionStages";
import styles from "./MermaidAgentDiagram.module.css";

export type ExecutionOutcome = Pick<ExecutionDetail,
  "status" | "answer_status" | "quality_status" | "duration_ms" | "observation_complete">;

const executionStates: Record<ExecutionOutcome["status"], { label: string; judgment: string }> = {
  running: { label: "진행 중", judgment: "실행 진행 중" },
  completed: { label: "처리 완료", judgment: "실행 완료" },
  failed: { label: "실행 실패", judgment: "실행 실패" },
  cancelled: { label: "취소", judgment: "실행 취소" },
  interrupted: { label: "중단", judgment: "실행 중단" },
};
const qualityStates = { unreviewed: "미검증", passed: "통과", failed: "실패" };
const answerStates: Record<string, string> = {
  answered: "답변 생성", insufficient_evidence: "근거 부족", not_requested: "생성 미요청", citation_validation_failed: "인용 오류",
};

export function ExecutionOutcomeSummary({ outcome }: { outcome?: ExecutionOutcome }) {
  const execution = outcome ? executionStates[outcome.status] : undefined;
  const quality = outcome ? qualityStates[outcome.quality_status] : "미기록";
  const answer = outcome?.answer_status;
  return <section aria-label="실행 결과 요약" className={styles.outcome}>
    <p className={styles.outcomeJudgment} data-quality={outcome?.quality_status}>
      {execution ? `${execution.judgment} · 품질 ${quality}` : "전체 실행 정보 미기록 · 품질 판단 불가"}
    </p>
    <dl className={styles.outcomeFacts}>
      <div><dt>실행</dt><dd>{execution?.label ?? "미기록"}</dd></div>
      <div><dt>답변</dt><dd>{answer ? answerStates[answer] ?? `기록된 상태: ${answer}` : "미기록"}</dd></div>
      <div data-quality={outcome?.quality_status}><dt>품질</dt><dd>{quality}</dd></div>
      <div><dt>전체 소요 시간</dt><dd>{duration(outcome?.duration_ms)}</dd></div>
    </dl>
    {outcome?.observation_complete === false ? <p className={styles.outcomeObservation}>전체 실행 관측 일부 누락</p> : null}
  </section>;
}
