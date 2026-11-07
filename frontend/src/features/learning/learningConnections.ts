import type { LearningSummary } from "./api";

export type LearningConnection = { status: "none" | "unknown" } | { status: "outside"; sourceStep: number } | { status: "connected"; sourceStep: number; sourceId: string };

/** Saved wording is evidence only for this exact relationship; ordinal proximity is not. */
export function resolveLearningConnections(records: LearningSummary[]): Map<string, LearningConnection> {
  return new Map(records.map((record): [string, LearningConnection] => {
    const sequence = record.learning_sequence;
    if (record.kind !== "experiment" || record.experiment_status === "planned" || sequence?.start_mode === "base_model") return [record.id, { status: "none" }];
    const match = sequence?.source_label?.trim().match(/^([1-9]\d*)차 학습 결과에서 이어 학습(?: · (?:예정 )?\d+회 추가 갱신(?: 완료)?)?$/);
    if (sequence?.start_mode !== "continued" || !match || !sequence.series?.trim() || !sequence.step) return [record.id, { status: "unknown" }];
    const sourceStep = Number(match[1]);
    if (!Number.isSafeInteger(sourceStep) || sourceStep >= sequence.step) return [record.id, { status: "unknown" }];
    const sources = records.filter(source => source.kind === "experiment" && source.learning_sequence?.series === sequence.series && source.learning_sequence.step === sourceStep);
    return [record.id, sources.length === 1 && sources[0].experiment_status !== "planned" ? { status: "connected", sourceId: sources[0].id, sourceStep } : sources.length > 0 ? { status: "unknown" } : { status: "outside", sourceStep }];
  }));
}
