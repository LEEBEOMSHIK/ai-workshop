import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { LearningEditor } from "./LearningEditor";
import { LearningListPage } from "./LearningListPage";
import { emptyExperiment } from "./registry";

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

it("starts one blank record without saving or asking users to choose a kind", async () => {
  const requests: RequestInit[] = [];
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    requests.push(init ?? {});
    return new Response(JSON.stringify(String(input).includes("records") ? { items: [], next_cursor: null } : []), { status: 200 });
  });
  vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup(); render(<LearningListPage />);
  await user.click(await screen.findByRole("button", { name: "새 기록" }));
  expect(screen.queryByRole("button", { name: "새 메모" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "새 실험" })).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "실험 항목 추가" })).not.toBeChecked();
  expect(screen.queryByRole("textbox", { name: "목적" })).not.toBeInTheDocument();
  expect(requests.every(request => !request.method || request.method === "GET")).toBe(true);
});

it("keeps unfinished metric input while excluding hidden experiment fields from note validation", async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  const user = userEvent.setup();
  render(<LearningEditor initialDraft={{ kind: "experiment", title: "기록", body: "원문", topic_keys: [], domain_labels: [], references: [], experiment: { ...emptyExperiment(), metrics: [{ name: "정확도", value: 0.5, unit: null }] } }} topics={[]} learningRecords={[]} evaluations={[]} submitLabel="저장" onSubmit={onSubmit} />);
  const toggle = screen.getByRole("checkbox", { name: "실험 항목 추가" });
  await user.clear(screen.getByRole("spinbutton", { name: "값" }));
  await user.type(screen.getByRole("textbox", { name: "새 지표 이름" }), "미완성 지표");
  await user.click(toggle);
  expect(screen.queryByRole("spinbutton", { name: "값" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "저장" }));
  expect(onSubmit).toHaveBeenCalledTimes(1);
  expect(onSubmit).toHaveBeenLastCalledWith(expect.objectContaining({ kind: "note", experiment: null }));
  await user.click(toggle);
  expect(screen.getByRole("spinbutton", { name: "값" })).toHaveValue(null);
  expect(screen.getByRole("textbox", { name: "새 지표 이름" })).toHaveValue("미완성 지표");
  await user.click(screen.getByRole("button", { name: "저장" }));
  expect(screen.getByRole("alert")).toHaveTextContent("지표 값은 비워 둘 수 없습니다");
  expect(onSubmit).toHaveBeenCalledTimes(1);
});

it("preserves experimental input across toggles and submits the selected mode", async () => {
  const onSubmit = vi.fn().mockResolvedValue(undefined);
  const confirm = vi.spyOn(window, "confirm");
  const user = userEvent.setup();
  render(<LearningEditor initialDraft={{ kind: "note", title: "기록", body: "원문", topic_keys: [], domain_labels: [], references: [], experiment: null }} topics={[]} learningRecords={[]} evaluations={[]} submitLabel="저장" onSubmit={onSubmit} />);
  const toggle = screen.getByRole("checkbox", { name: "실험 항목 추가" });
  await user.click(toggle);
  await user.type(screen.getByRole("textbox", { name: "목적" }), "비교 목적");
  await user.click(toggle);
  await user.click(screen.getByRole("button", { name: "저장" }));
  expect(onSubmit).toHaveBeenLastCalledWith(expect.objectContaining({ kind: "note", experiment: null, body: "원문" }));
  await user.click(toggle);
  expect(screen.getByRole("textbox", { name: "목적" })).toHaveValue("비교 목적");
  await user.click(screen.getByRole("button", { name: "저장" }));
  expect(onSubmit).toHaveBeenLastCalledWith(expect.objectContaining({ kind: "experiment", experiment: expect.objectContaining({ purpose: "비교 목적" }) }));
  expect(confirm).not.toHaveBeenCalled();
});
