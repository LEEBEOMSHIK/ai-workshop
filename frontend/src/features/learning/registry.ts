import type {
  ExperimentFields,
  ExperimentStatus,
  RecordKind,
  TroubleshootingFields,
} from "./api";

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
