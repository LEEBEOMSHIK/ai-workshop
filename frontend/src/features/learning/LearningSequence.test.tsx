import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { LearningEditor } from "./LearningEditor";
import { LearningListPage } from "./LearningListPage";
import { LearningRecordReader } from "./LearningRecordReader";
import type { LearningDraft, LearningRecord, LearningSummary } from "./api";
import { emptyExperiment } from "./registry";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const dates = { created_at: "2026-01-01T00:00:00Z", updated_at: "2026-02-01T00:00:00Z" };
const series = "합성 규정 학습";
const progressDefaults = { start_mode: "unknown", outcome_status: "not_evaluated" } as const;
function summary(id: string, step: number | null, status: "planned" | "completed" = "completed"): LearningSummary {
  return { id, title: `기록 ${id}`, kind: "experiment", topic_keys: ["fine-tuning"], revision: 1,
    ...dates, archived_at: null, experiment_status: status,
    learning_sequence: { ...progressDefaults, series, step, performed_on: status === "planned" ? null : "2026-01-03" } };
}
function draft(): LearningDraft {
  return { title: "합성 학습", body: "기존 본문", kind: "experiment", topic_keys: ["fine-tuning"], domain_labels: [], references: [],
    experiment: { ...emptyExperiment(), status: "completed", learning_sequence: { ...progressDefaults, series, step: 3, performed_on: "2026-01-03" } } };
}
function response(value: unknown) { return new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } }); }
function mockList(items: LearningSummary[], paths: string[] = []) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input); paths.push(path);
    if (path === "/api/v1/learning/topics") return response([{ key: "fine-tuning", label: "Fine-tuning" }]);
    if (path.startsWith("/api/v1/rag/evaluation-runs")) return response([]);
    return response({ items, next_cursor: null });
  }));
}

describe("explicit learning sequence", () => {
  it("shows saved steps and separates a plan without inferring order from modified dates", async () => {
    const items = [summary("first", 1), summary("fourth", 4), summary("plan", null, "planned")];
    const paths: string[] = []; mockList(items, paths);
    render(<LearningListPage />);
    expect(await screen.findByText("1차 학습")).toBeVisible();
    expect(screen.getByText("4차 학습")).toBeVisible();
    expect(screen.queryByText("2차 학습")).not.toBeInTheDocument();
    expect(screen.getByText("계획 · 미실행")).toBeVisible();
    expect(screen.getByRole("list", { name: "학습 기록 흐름" })).toBeVisible();
    expect(screen.getAllByText("실행 2026. 1. 3.")).toHaveLength(2);
    expect(paths.some(path => path.includes("sort=learning_latest"))).toBe(true);
    const links = within(screen.getByRole("list", { name: "학습 기록 흐름" })).getAllByRole("link");
    expect(links.map(link => link.textContent)).toEqual(["기록 first", "기록 fourth", "기록 plan"]);
    expect(screen.getByText("관련 계획 · 실행 차수에 포함하지 않음")).toBeVisible();
  });

  it("leaves unrecorded sequence unknown and changes the server sort explicitly", async () => {
    const paths: string[] = []; mockList([{ ...summary("unknown", null), learning_sequence: null }], paths);
    const user = userEvent.setup(); render(<LearningListPage />);
    expect(await screen.findByText("차수 미기록")).toBeVisible();
    expect(screen.queryByText("1차 학습")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "정렬" }), "updated");
    await waitFor(() => expect(paths.some(path => path.includes("sort=updated"))).toBe(true));
  });

  it("preserves explicit sequence and existing content when editing", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined); const user = userEvent.setup();
    render(<LearningEditor initialDraft={draft()} topics={[]} learningRecords={[]} evaluations={[]} submitLabel="저장" onSubmit={onSubmit} />);
    expect(screen.getByRole("textbox", { name: "학습 흐름 이름" })).toHaveValue(series);
    expect(screen.getByRole("spinbutton", { name: "학습 차수" })).toHaveValue(3);
    expect(screen.getByLabelText("실제 실행일")).toHaveValue("2026-01-03");
    await user.clear(screen.getByRole("spinbutton", { name: "학습 차수" }));
    await user.type(screen.getByRole("spinbutton", { name: "학습 차수" }), "4");
    await user.click(screen.getByRole("button", { name: "저장" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ body: "기존 본문", experiment: expect.objectContaining({ learning_sequence: { ...progressDefaults, series, step: 4, performed_on: "2026-01-03" } }) }));
  });

  it.each(["change", "input"] as const)("saves a newly entered calendar date after a native %s event", async (eventName) => {
    const initial = draft();
    initial.experiment = { ...initial.experiment!, learning_sequence: { ...progressDefaults, series, step: 1, performed_on: null } };
    const onSubmit = vi.fn().mockResolvedValue(undefined); const user = userEvent.setup();
    render(<LearningEditor initialDraft={initial} topics={[]} learningRecords={[]} evaluations={[]} submitLabel="저장" onSubmit={onSubmit} />);
    const date = screen.getByLabelText("실제 실행일");
    fireEvent[eventName](date, { target: { value: "2026-01-04" } });
    await user.tab();
    // A different controlled change also verifies that a render keeps the entered date.
    await user.clear(screen.getByRole("spinbutton", { name: "학습 차수" }));
    await user.type(screen.getByRole("spinbutton", { name: "학습 차수" }), "2");
    expect(date).toHaveValue("2026-01-04");
    await user.click(screen.getByRole("button", { name: "저장" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ experiment: expect.objectContaining({ learning_sequence: { ...progressDefaults, series, step: 2, performed_on: "2026-01-04" } }) }));
  });

  it("resets the page cursor when switching sort and never renumbers filtered records", async () => {
    const paths: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input); paths.push(path);
      if (path === "/api/v1/learning/topics") return response([]);
      if (path.startsWith("/api/v1/rag/evaluation-runs")) return response([]);
      if (path.includes("sort=updated")) return response({ items: [summary("saved-step", 8)], next_cursor: null });
      return response({ items: [summary(path.includes("cursor=") ? "second-page" : "first-page", 8)], next_cursor: path.includes("cursor=") ? null : "page-two" });
    }));
    const user = userEvent.setup(); render(<LearningListPage />);
    await screen.findByText("기록 first-page");
    await user.click(screen.getByRole("button", { name: "다음 페이지" }));
    await screen.findByText("기록 second-page");
    expect(screen.getByText("8차 학습")).toBeVisible();
    await user.selectOptions(screen.getByRole("combobox", { name: "정렬" }), "updated");
    await screen.findByText("기록 saved-step");
    expect(paths.filter(path => path.includes("sort=updated")).every(path => !path.includes("cursor="))).toBe(true);
    expect(screen.getByText("8차 학습")).toBeVisible();
    expect(screen.getByRole("button", { name: "이전 페이지" })).toBeDisabled();
  });

  it("does not silently save a blank flow name or manufacture a first step", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined); const user = userEvent.setup();
    render(<LearningEditor initialDraft={draft()} topics={[]} learningRecords={[]} evaluations={[]} submitLabel="저장" onSubmit={onSubmit} />);
    await user.clear(screen.getByRole("textbox", { name: "학습 흐름 이름" }));
    await user.type(screen.getByRole("textbox", { name: "학습 흐름 이름" }), "   ");
    await user.click(screen.getByRole("button", { name: "저장" }));
    expect(onSubmit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("학습 흐름 이름을 입력");
    await user.clear(screen.getByRole("textbox", { name: "학습 흐름 이름" }));
    await user.type(screen.getByRole("textbox", { name: "학습 흐름 이름" }), series);
    await user.clear(screen.getByRole("spinbutton", { name: "학습 차수" }));
    await user.click(screen.getByRole("button", { name: "저장" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ experiment: expect.objectContaining({ learning_sequence: { ...progressDefaults, series, step: null, performed_on: "2026-01-03" } }) }));
  });

  it("clears execution-only metadata when a record becomes a plan", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined); const user = userEvent.setup();
    render(<LearningEditor initialDraft={draft()} topics={[]} learningRecords={[]} evaluations={[]} submitLabel="저장" onSubmit={onSubmit} />);
    await user.selectOptions(screen.getByRole("combobox", { name: "실험 상태" }), "planned");
    expect(screen.getByRole("spinbutton", { name: "학습 차수" })).toBeDisabled();
    expect(screen.getByLabelText("실제 실행일")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "저장" }));
    expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ experiment: expect.objectContaining({ status: "planned", learning_sequence: { ...progressDefaults, series, step: null, performed_on: null, outcome_status: "not_evaluated", outcome: null, remaining: null } }) }));
  });

  it("shows the same saved sequence on the reader without inferring reference ancestry", () => {
    const record: LearningRecord = { id: "record", revision: 1, ...dates, archived_at: null, draft: draft(), reference_views: [], dataset_reference_view: null, unavailable_reference_count: 0 };
    render(<LearningRecordReader record={record} records={[]} evaluations={[]} />);
    const sequence = screen.getByRole("region", { name: "학습 순서" });
    expect(within(sequence).getByText("3차 학습")).toBeVisible();
    expect(within(sequence).getByText(series)).toBeVisible();
    expect(within(sequence).getByText("2026. 1. 3.")).toBeVisible();
    expect(screen.queryByText(/이전 모델/)).not.toBeInTheDocument();
  });
});
