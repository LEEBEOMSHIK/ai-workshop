import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { LearningSequenceList } from "./LearningSequence";
import type { LearningSummary } from "./api";

afterEach(() => { cleanup(); vi.restoreAllMocks(); });
function record(id: string, step: number, start: "base_model" | "continued" | "unknown", source?: string): LearningSummary {
  return { id, title: `기록 ${id}`, kind: "experiment", topic_keys: [], revision: 1,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", archived_at: null,
    experiment_status: "completed", learning_sequence: { series: "같은 흐름", step, performed_on: "2026-01-01", start_mode: start, source_label: source, outcome_status: "not_evaluated" } };
}

it.each([true, false])("uses saved source names rather than adjacent records when ordered=%s", (ordered) => {
  const { container } = render(<LearningSequenceList ordered={ordered} topics={[]} records={[
    record("continued", 4, "continued", "별도 실험에서 저장한 어댑터"), record("base", 3, "base_model"), record("unknown", 2, "unknown"),
  ]} />);
  expect(container.querySelector("[data-continues]")).toBeNull();
  const continued = within(screen.getByRole("link", { name: "기록 continued" })).getByRole("group", { name: "학습 출발 관계" });
  expect(within(continued).getByText("별도 실험에서 저장한 어댑터")).toBeVisible();
  expect(within(continued).getByText("이전 학습 결과에서 계속")).toBeVisible();
  expect(within(continued).getByText("연결 미확인")).toBeVisible();
  expect(within(screen.getByRole("link", { name: "기록 continued" })).getByText("4차 학습")).toBeVisible();
  const base = screen.getByRole("link", { name: "기록 base" });
  expect(within(base).getByText("원본 모델에서 시작")).toBeVisible();
  expect(within(base).queryByText("이어 학습")).not.toBeInTheDocument();
  const unknown = screen.getByRole("link", { name: "기록 unknown" });
  expect(within(unknown).getByText("출발점 미확인")).toBeVisible();
  expect(within(unknown).queryByText("이어 학습")).not.toBeInTheDocument();
  expect(within(unknown).queryByText("이번 2차 학습")).not.toBeInTheDocument();
});

it.each([false, true])("draws only the saved nonadjacent relationship with chronological direction, reversed=%s", reverse => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function(this: HTMLElement) {
    const markers = Array.from(document.querySelectorAll("[data-connection-anchor]"));
    const index = markers.indexOf(this);
    return { x: 24, y: index * 100, left: index < 0 ? 0 : 24, top: index < 0 ? 0 : index * 100, width: 50, height: 36, right: 74, bottom: index * 100 + 36, toJSON() {} };
  });
  const records = [record("target", 3, "continued", "1차 학습 결과에서 이어 학습"), record("unrelated", 2, "base_model"), record("source", 1, "base_model")];
  const { container } = render(<LearningSequenceList ordered={!reverse} topics={[]} startIndex={5} records={reverse ? records.reverse() : records} />);
  expect(screen.getByLabelText("목록 순번 6")).toHaveAttribute("aria-label", "목록 순번 6");
  expect(screen.getByLabelText("목록 순번 6")).toHaveTextContent(/^6$/);
  expect(screen.getByLabelText("목록 순번 8")).toBeVisible();
  expect(screen.getByLabelText("목록 순번 6")).toHaveAttribute("data-connection-anchor");
  expect(screen.getByLabelText("목록 순번 6").closest("a")).toBeNull();
  expect(screen.getByText("1차 학습 → 3차 학습 · 이어 학습")).toBeVisible();
  const paths = container.querySelectorAll("svg > path[marker-end]");
  expect(paths).toHaveLength(1);
  expect(container.querySelectorAll("[data-card-association]")).toHaveLength(3);
  expect(paths[0].getAttribute("d")).toBe(reverse ? "M 24 18 H 2 V 218 H 21" : "M 24 218 H 2 V 18 H 21");
});

it("does not assert ancestry for a blank source or an unexecuted plan", () => {
  const plan = { ...record("plan", 5, "continued", "선행 실험"), experiment_status: "planned" as const };
  const { container } = render(<LearningSequenceList ordered topics={[]} records={[record("blank", 4, "continued", "   "), plan]} />);
  expect(container.querySelectorAll("[data-card-association]")).toHaveLength(2);
  expect(container.querySelectorAll("svg > path[marker-end]")).toHaveLength(0);
  const blank = screen.getByRole("link", { name: "기록 blank" });
  expect(within(blank).getByText("출발점 미확인")).toBeVisible();
  expect(within(blank).queryByText("이어 학습")).not.toBeInTheDocument();
  expect(within(screen.getByRole("link", { name: "기록 plan" })).queryByRole("group", { name: "학습 출발 관계" })).not.toBeInTheDocument();
});

it.each([false, true])("connects adjacent circles toward the later learning step, reversed=%s", reverse => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function(this: HTMLElement) {
    const index = Array.from(document.querySelectorAll("[data-connection-anchor]")).indexOf(this);
    return { left: index < 0 ? 0 : 24, top: index < 0 ? 0 : index * 100, width: 44, height: 44, bottom: index * 100 + 44, right: 68, x: 24, y: index * 100, toJSON() {} };
  });
  const records = [record("second", 2, "continued", "1차 학습 결과에서 이어 학습"), record("first", 1, "base_model")];
  const { container } = render(<LearningSequenceList ordered topics={[]} records={reverse ? records.reverse() : records} />);
  expect(container.querySelector("svg > path[marker-end]")).toHaveAttribute("d", reverse ? "M 46 44 V 97" : "M 46 100 V 47");
  expect(screen.getByLabelText("목록 순번 1")).toHaveTextContent(/^1$/);
  expect(screen.getByText("2차 학습")).toBeVisible();
  expect(screen.queryByText("순번")).not.toBeInTheDocument();
});
