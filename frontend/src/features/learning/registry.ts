import type {
  ExperimentFields,
  ExperimentStatus,
  RecordKind,
  TroubleshootingFields,
} from "./api";

export const learningPageSizeOptions = [
  { value: 5, label: "5개" },
  { value: 10, label: "10개" },
  { value: 20, label: "20개" },
] as const;
export type LearningPageSize = (typeof learningPageSizeOptions)[number]["value"];
export const defaultLearningPageSize: LearningPageSize = 5;

export const recordKindOptions: ReadonlyArray<{ value: RecordKind; label: string }> = [
  { value: "note", label: "자유 메모" },
  { value: "experiment", label: "구조화 실험" },
];

export const experimentStatusOptions: ReadonlyArray<{
  value: ExperimentStatus;
  label: string;
}> = [
  { value: "planned", label: "계획" },
  { value: "running", label: "진행 중" },
  { value: "completed", label: "수행 완료" },
  { value: "failed", label: "실패" },
  { value: "cancelled", label: "취소" },
];

type Sequence = NonNullable<ExperimentFields["learning_sequence"]>;
export const learningStartOptions: ReadonlyArray<{ value: NonNullable<Sequence["start_mode"]>; label: string }> = [
  { value: "unknown", label: "출발점 미확인" },
  { value: "base_model", label: "원본 모델에서 시작" },
  { value: "continued", label: "이전 학습 결과에서 계속" },
];
export const learningOutcomeOptions: ReadonlyArray<{ value: NonNullable<Sequence["outcome_status"]>; label: string }> = [
  { value: "not_evaluated", label: "미평가" },
  { value: "improved", label: "개선 확인" },
  { value: "no_improvement", label: "개선 관찰되지 않음" },
  { value: "mixed", label: "일부 개선 · 한계 있음" },
];

export function emptyTroubleshooting(): TroubleshootingFields {
  return {
    symptom: null,
    reproduction: null,
    facts: [],
    hypotheses: [],
    confirmed_cause: null,
    change: null,
    verification: null,
    unresolved: [],
  };
}

export function emptyExperiment(): ExperimentFields {
  return {
    status: "planned",
    purpose: null,
    hypothesis: null,
    dataset_snapshot: null,
    configurations: [],
    environment: null,
    procedure: null,
    observations: null,
    metrics: [],
    limitations: null,
    conclusion: null,
    next_steps: [],
    troubleshooting: null,
  };
}
