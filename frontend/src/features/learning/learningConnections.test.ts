import { expect, it } from "vitest";
import type { LearningSummary } from "./api";
import { resolveLearningConnections } from "./learningConnections";

it("recognizes an explicitly completed update description without inferring a different parent", () => {
  const target = record("target", 4, "3차 학습 결과에서 이어 학습 · 6회 추가 갱신 완료");
  expect(resolveLearningConnections([target, record("parent", 3)]).get("target")).toEqual({ status: "connected", sourceId: "parent", sourceStep: 3 });
});

function record(id: string, step: number, source?: string): LearningSummary {
  return { id, title: id, kind: "experiment", topic_keys: [], revision: 1, created_at: "2026-01-01", updated_at: "2026-01-01", archived_at: null, experiment_status: "completed", learning_sequence: { series: "흐름", outcome_status: "not_evaluated", step, start_mode: source ? "continued" : "base_model", source_label: source } };
}
it.each([false, true])("connects explicit ancestry across intervening unrelated cards in either order %s", reverse => {
  const records = [record("third", 3, "1차 학습 결과에서 이어 학습 · 12회 추가 갱신"), record("second", 2), record("first", 1)];
  const result = resolveLearningConnections(reverse ? records.reverse() : records);
  expect(result.get("third")).toEqual({ status: "connected", sourceId: "first", sourceStep: 1 });
  expect(result.get("second")).toEqual({ status: "none" });
});
it.each(["1차 학습 결과에서 이어 학습하지 않음", "1차 학습 결과에서 이어 학습 안 함", "1차 학습 결과에서 이어 학습 · 2차 학습도 사용", "별도 어댑터", " "])("does not infer a source from %s", source => {
  const target = record("target", 3, source);
  expect(resolveLearningConnections([target, record("first", 1)]).get("target")).toEqual({ status: "unknown" });
});
it("distinguishes missing, ambiguous, future, unknown and unexecuted sources", () => {
  const target = record("target", 3, "1차 학습 결과에서 이어 학습");
  expect(resolveLearningConnections([target]).get("target")).toEqual({ status: "outside", sourceStep: 1 });
  expect(resolveLearningConnections([target, record("a", 1), record("b", 1)]).get("target")).toEqual({ status: "unknown" });
  expect(resolveLearningConnections([record("bad", 1, "2차 학습 결과에서 이어 학습")]).get("bad")).toEqual({ status: "unknown" });
  expect(resolveLearningConnections([{ ...target, experiment_status: "planned" }]).get("target")).toEqual({ status: "none" });
  target.learning_sequence!.start_mode = "unknown";
  expect(resolveLearningConnections([target]).get("target")).toEqual({ status: "unknown" });
});
it("never connects different series or a planned source", () => {
  const target = record("target", 3, "1차 학습 결과에서 이어 학습");
  const source = record("source", 1);
  source.learning_sequence!.series = "다른 흐름";
  expect(resolveLearningConnections([target, source]).get("target")).toEqual({ status: "outside", sourceStep: 1 });
  source.learning_sequence!.series = "흐름";
  source.experiment_status = "planned";
  expect(resolveLearningConnections([target, source]).get("target")).toEqual({ status: "unknown" });
});
