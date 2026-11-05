import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LearningEditor } from "./LearningEditor";
import { LearningListPage } from "./LearningListPage";
import { LearningSequenceDetail, LearningSequenceList } from "./LearningSequence";
import type { ExperimentFields, LearningDraft, LearningSummary } from "./api";
import { emptyExperiment } from "./registry";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });
type Sequence = NonNullable<ExperimentFields["learning_sequence"]>;
const sequence: Sequence = {
  series: "합성 응답 실험", step: 3, performed_on: "2026-01-03",
  start_mode: "continued", source_label: "두 번째 실험의 어댑터", source_evidence: "입력 파일 식별값을 실행 기록과 대조함",
  objective: "질문한 기간을 생략하지 않기", outcome_status: "mixed",
  outcome: "학습 문항 한 개에서 기간 누락을 수정함", remaining: "미사용 질문의 개선은 확인되지 않음",
};
const draft = (): LearningDraft => ({ title: "합성 학습", body: "기존 원문과 [e9]", kind: "experiment", topic_keys: [], domain_labels: [], references: [], experiment: { ...emptyExperiment(), status: "completed", learning_sequence: sequence } });
const summary = (id: string, step: number): LearningSummary => ({ id, title: `실험 ${id}`, kind: "experiment", topic_keys: [], revision: 1, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-02-01T00:00:00Z", archived_at: null, experiment_status: "completed", learning_sequence: { ...sequence, step } });
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 200 });

describe("learning origin and measured progress", () => {
  it("shows all topic labels directly below the title as noninteractive classification", () => {
    const record = { ...summary("topics", 3), topic_keys: ["fine-tuning", "rag", "unregistered-topic"] };
    render(<LearningSequenceList records={[record]} topics={[{ key: "fine-tuning", label: "Fine-tuning" }, { key: "rag", label: "RAG" }]} ordered />);
    const classification = screen.getByRole("group", { name: "기술 주제" });
    expect(within(classification).getByText("Fine-tuning")).toBeVisible();
    expect(within(classification).getByText("RAG")).toBeVisible();
    expect(within(classification).getByText("unregistered-topic")).toBeVisible();
    expect(within(classification).queryByRole("button")).not.toBeInTheDocument();
    expect(within(classification).queryByRole("link")).not.toBeInTheDocument();
    const title = screen.getByRole("heading", { name: "실험 topics" });
    expect(title.nextElementSibling).toBe(classification);
    expect(classification.textContent).not.toContain("수행 완료");
  });

  it("labels the record kind when no topics have been recorded", () => {
    render(<LearningSequenceList records={[{ ...summary("memo", 1), kind: "note", learning_sequence: null }]} topics={[]} ordered />);
    expect(within(screen.getByRole("group", { name: "기록 종류" })).getByText("자유 메모")).toBeVisible();
    expect(screen.queryByRole("group", { name: "기술 주제" })).not.toBeInTheDocument();
  });

  it("requests latest steps by default and preserves the server's global ordering", async () => {
    const paths: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input); paths.push(path);
      if (path.includes("topics") || path.includes("evaluation-runs")) return response([]);
      return response({ items: [summary("third", 3), summary("second", 2), summary("first", 1)], next_cursor: null });
    }));
    render(<LearningListPage />);
    await screen.findByText("3차 학습");
    expect(screen.getByRole("combobox", { name: "정렬" })).toHaveValue("learning_latest");
    expect(paths.some(path => path.includes("sort=learning_latest"))).toBe(true);
    const links = within(screen.getByRole("list", { name: "학습 기록 흐름" })).getAllByRole("link");
    ["실험 third", "실험 second", "실험 first"].forEach((title, index) => expect(links[index]).toHaveAccessibleName(title));
  });

  it("shows explicit origin, objective, qualified outcome and remaining problems on cards", () => {
    render(<LearningSequenceList records={[summary("example", 3)]} topics={[]} ordered />);
    expect(screen.getByText("이전 학습 결과에서 계속")).toBeVisible();
    expect(screen.getByText(sequence.source_label!)).toBeVisible();
    expect(screen.getByText(sequence.objective!)).toBeVisible();
    expect(screen.getByText(sequence.outcome!)).toBeVisible();
    expect(screen.getByText(sequence.remaining!)).toBeVisible();
    expect(screen.getByText("일부 개선 · 한계 있음")).toBeVisible();
    expect(screen.queryByText(sequence.source_evidence!)).not.toBeInTheDocument();
  });

  it("distinguishes an original-model start from unknown ancestry even for numbered records", () => {
    const base = summary("base", 1); base.learning_sequence = { ...sequence, start_mode: "base_model", source_label: "기반 모델", outcome_status: "no_improvement" };
    // Older cached responses can predate these optional storage fields.
    const unknown = summary("unknown", 4); unknown.learning_sequence = { series: "다른 흐름", step: 4, performed_on: null } as Sequence;
    render(<LearningSequenceList records={[base, unknown]} topics={[]} ordered />);
    expect(screen.getByText("원본 모델에서 시작")).toBeVisible();
    expect(screen.getByText("출발점 미확인")).toBeVisible();
    expect(screen.getByText("미평가")).toBeVisible();
    expect(screen.getByText("개선 관찰되지 않음")).toBeVisible();
  });

  it("keeps source evidence available in a keyboard-operable detail disclosure", async () => {
    const user = userEvent.setup();
    render(<LearningSequenceDetail value={sequence} status="completed" />);
    const disclosure = screen.getByText("출발점 확인 근거").closest("summary")!;
    expect(disclosure.closest("details")).not.toHaveAttribute("open");
    await user.click(disclosure);
    expect(disclosure.closest("details")).toHaveAttribute("open");
    expect(screen.getByText(sequence.source_evidence!)).toBeVisible();
  });

  it("does not present planned or missing outcome text as a measured success", () => {
    const planned = { ...summary("plan", 1), experiment_status: "planned" as const };
    render(<LearningSequenceList records={[planned, { ...summary("missing", 2), learning_sequence: { ...sequence, outcome: null, outcome_status: "improved" } }]} topics={[]} ordered />);
    const cards = screen.getAllByRole("article");
    expect(within(cards[0]).queryByText("확인된 결과")).not.toBeInTheDocument();
    expect(within(cards[0]).queryByText("이전 학습 결과에서 계속")).not.toBeInTheDocument();
    expect(within(cards[1]).getByText("미평가")).toBeVisible();
    expect(screen.queryByText("개선 확인")).not.toBeInTheDocument();
  });

  it("edits metadata while preserving the original body and evaluation fields", async () => {
    const user = userEvent.setup(); const onSubmit = vi.fn().mockResolvedValue(undefined); const initial = draft();
    render(<LearningEditor initialDraft={initial} topics={[]} learningRecords={[]} evaluations={[]} submitLabel="저장" onSubmit={onSubmit} />);
    await user.clear(screen.getByRole("textbox", { name: "개선 목표 요약" }));
    await user.type(screen.getByRole("textbox", { name: "개선 목표 요약" }), "조건 누락 방지");
    await user.click(screen.getByRole("button", { name: "저장" }));
    expect(onSubmit).toHaveBeenCalledWith({ ...initial, experiment: { ...initial.experiment, learning_sequence: { ...sequence, objective: "조건 누락 방지" } } });
  });

  it("requires a source for continued training and a description for an evaluated outcome", async () => {
    const user = userEvent.setup(); const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<LearningEditor initialDraft={draft()} topics={[]} learningRecords={[]} evaluations={[]} submitLabel="저장" onSubmit={onSubmit} />);
    await user.clear(screen.getByRole("textbox", { name: "출발 모델·학습 결과" }));
    await user.type(screen.getByRole("textbox", { name: "출발 모델·학습 결과" }), "   ");
    await user.click(screen.getByRole("button", { name: "저장" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("이어 학습한 출발점");
    await user.selectOptions(screen.getByRole("combobox", { name: "학습 출발 방식" }), "base_model");
    await user.clear(screen.getByRole("textbox", { name: "확인된 결과 요약" }));
    await user.type(screen.getByRole("textbox", { name: "확인된 결과 요약" }), "   ");
    await user.click(screen.getByRole("button", { name: "저장" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("판정의 근거가 되는 결과");
  });

  it("clears actual results on conversion to a plan while retaining its intended objective", async () => {
    const user = userEvent.setup(); const onSubmit = vi.fn().mockResolvedValue(undefined);
    render(<LearningEditor initialDraft={draft()} topics={[]} learningRecords={[]} evaluations={[]} submitLabel="저장" onSubmit={onSubmit} />);
    await user.selectOptions(screen.getByRole("combobox", { name: "실험 상태" }), "planned");
    expect(screen.getByRole("combobox", { name: "결과 판정" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "저장" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ experiment: expect.objectContaining({ learning_sequence: expect.objectContaining({ objective: sequence.objective, outcome_status: "not_evaluated", outcome: null, remaining: null, step: null, performed_on: null }) }) }));
  });
});
