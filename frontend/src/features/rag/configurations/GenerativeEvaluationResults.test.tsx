import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { GenerativeEvaluationResults } from "./GenerativeEvaluationResults";
import type { GenerativeRun } from "./generative-api";

type Attempt = GenerativeRun["attempts"][number];
function attempt(id: string, status = "completed", correctness = "passed", generation_status = "answered") {
  return { id, case_id: id, query: `질문 ${id}`, status, configuration_version_id: "config", repetition: 0, attempt_number: 1,
    observation: { generation_status }, metrics: { correctness, citation_valid: true }, answer: `답변 ${id}` } as Attempt;
}
function Harness({ attempts, initial = "" }: { attempts: Attempt[]; initial?: string }) {
  const [caseId, setCaseId] = useState(initial);
  return <GenerativeEvaluationResults run={{ attempts } as GenerativeRun} caseId={caseId} onSelect={setCaseId} renderAttempt={item => <article key={item.id}>{item.answer}</article>} />;
}
it("filters questions using latest attempts and keeps historical failures out of current status", () => {
  const old = { ...attempt("recovered", "failed"), id: "old", answer: "과거 실패" };
  const latest = { ...attempt("recovered"), attempt_number: 2 };
  render(<Harness attempts={[old, latest, attempt("failure", "failed"), attempt("abstain", "completed", "passed", "insufficient_evidence"), attempt("review", "completed", "unreviewed"), attempt("pending", "pending")]} />);
  fireEvent.change(screen.getByRole("combobox", { name: "질문 상태" }), { target: { value: "실패" } });
  expect(screen.getByRole("button", { name: /질문 failure/ })).toBeVisible();
  expect(screen.queryByRole("button", { name: /질문 recovered/ })).not.toBeInTheDocument();
  fireEvent.change(screen.getByRole("combobox", { name: "질문 상태" }), { target: { value: "근거 부족" } });
  expect(screen.getByRole("button", { name: /질문 abstain/ })).toBeVisible();
  fireEvent.change(screen.getByRole("combobox", { name: "질문 상태" }), { target: { value: "검토 필요" } });
  expect(screen.getByRole("button", { name: /질문 review/ })).toBeVisible();
  fireEvent.change(screen.getByRole("combobox", { name: "질문 상태" }), { target: { value: "진행 중" } });
  expect(screen.getByRole("button", { name: /질문 pending/ })).toBeVisible();
});
it("renders only the selected question and latest repetition, revealing retry history explicitly", async () => {
  const latest = { ...attempt("first"), id: "latest", attempt_number: 2, answer: "최신 답변" };
  render(<Harness attempts={[attempt("first"), latest, attempt("second")]} />);
  expect(screen.getByText("최신 답변")).toBeVisible();
  expect(screen.queryByText("답변 first")).not.toBeInTheDocument();
  expect(screen.queryByText("답변 second")).not.toBeInTheDocument();
  fireEvent.click(screen.getByText("이 반복의 이전 시도 1건"));
  expect(await screen.findByText("답변 first")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /질문 second/ }));
  expect(screen.getByText("답변 second")).toBeVisible();
  const result = screen.getByRole("complementary", { name: "평가 질문 목록" }).parentElement;
  expect(result).toHaveAttribute("data-mobile-detail", "true");
  fireEvent.click(screen.getByRole("button", { name: "질문 목록으로" }));
  expect(result).toHaveAttribute("data-mobile-detail", "false");
});

it("selects a matching question when filtering and clears stale details for zero results", () => {
  render(<Harness attempts={[attempt("good"), attempt("bad", "failed")]} initial="good" />);
  expect(screen.getByRole("complementary", { name: "평가 질문 목록" }).parentElement).toHaveAttribute("data-mobile-detail", "true");
  fireEvent.change(screen.getByRole("combobox", { name: "질문 상태" }), { target: { value: "실패" } });
  expect(screen.getByText("답변 bad")).toBeVisible();
  expect(screen.queryByText("답변 good")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /질문 bad/ })).toHaveAttribute("aria-pressed", "true");
  fireEvent.change(screen.getByLabelText("질문 검색"), { target: { value: "no matches" } });
  expect(screen.queryByText("답변 bad")).not.toBeInTheDocument();
  expect(screen.getByText("표시할 질문이 없습니다. 검색어나 상태 필터를 변경하세요.")).toBeVisible();
});

it("moves the selection when refreshed judgments remove the current case from the filter", async () => {
  const attempts = [attempt("a", "completed", "unreviewed"), attempt("b", "completed", "unreviewed")];
  const { rerender } = render(<Harness attempts={attempts} initial="a" />);
  fireEvent.change(screen.getByRole("combobox", { name: "질문 상태" }), { target: { value: "검토 필요" } });
  expect(screen.getByText("답변 a")).toBeVisible();
  rerender(<Harness attempts={[attempt("a"), attempts[1]]} initial="a" />);
  expect(await screen.findByText("답변 b")).toBeVisible();
  expect(screen.queryByText("답변 a")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /질문 b/ })).toHaveAttribute("aria-pressed", "true");
});

it("shows five questions per page and initially includes the deep-linked question", () => {
  render(<Harness attempts={Array.from({ length: 12 }, (_, i) => attempt(`q${i}`))} initial="q7" />);
  expect(screen.getByText("2 / 3 페이지")).toBeVisible();
  expect(screen.getByRole("button", { name: /질문 q7/ })).toHaveAttribute("aria-pressed", "true");
  expect(screen.queryByRole("button", { name: /질문 q0/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "다음 질문 페이지" }));
  expect(screen.getByText("3 / 3 페이지")).toBeVisible();
  expect(screen.getByText("답변 q10")).toBeVisible();
});

it("mounts only the selected comparison tab", () => {
  render(<GenerativeEvaluationResults run={{ attempts: [attempt("a")] } as GenerativeRun} caseId="a" onSelect={() => {}} renderAttempt={(item, view) => <article key={item.id}>{view} content</article>} />);
  expect(screen.getByText("answer content")).toBeVisible();
  expect(screen.queryByText("evidence content")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "근거·진단" }));
  expect(screen.getByText("evidence content")).toBeVisible();
  expect(screen.queryByText("answer content")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("tab", { name: "검토" }));
  expect(screen.getByText("review content")).toBeVisible();
  expect(screen.queryByText("evidence content")).not.toBeInTheDocument();
});

it("changes repetitions with the labeled selector and resets to the first repetition for another question", () => {
  const second = { ...attempt("a"), id: "a-repeat", repetition: 1, answer: "두 번째 반복 답변" };
  render(<Harness attempts={[attempt("a"), second, attempt("b")]} />);
  fireEvent.change(screen.getByRole("combobox", { name: "반복" }), { target: { value: "1" } });
  expect(screen.getByText("두 번째 반복 답변")).toBeVisible();
  expect(screen.queryByText("답변 a")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /질문 b/ }));
  expect(screen.getByRole("combobox", { name: "반복" })).toHaveValue("0");
  expect(screen.getByText("답변 b")).toBeVisible();
});

it("supports roving keyboard focus and activation for comparison tabs", () => {
  render(<GenerativeEvaluationResults run={{ id: "keyboard", attempts: [attempt("a")] } as GenerativeRun} caseId="a" onSelect={() => {}} renderAttempt={(item, view) => <article key={item.id}>{view} content</article>} />);
  const answer = screen.getByRole("tab", { name: "답변 비교" });
  const evidence = screen.getByRole("tab", { name: "근거·진단" });
  const review = screen.getByRole("tab", { name: "검토" });
  expect(answer).toHaveAttribute("tabindex", "0");
  expect(evidence).toHaveAttribute("tabindex", "-1");
  answer.focus();
  fireEvent.keyDown(answer, { key: "ArrowRight" });
  expect(evidence).toHaveFocus();
  expect(evidence).toHaveAttribute("aria-selected", "true");
  expect(screen.getByText("evidence content")).toBeVisible();
  fireEvent.keyDown(evidence, { key: "End" });
  expect(review).toHaveFocus();
  fireEvent.keyDown(review, { key: "ArrowRight" });
  expect(answer).toHaveFocus();
  fireEvent.keyDown(answer, { key: "ArrowLeft" });
  expect(review).toHaveFocus();
  fireEvent.keyDown(review, { key: "Home" });
  expect(answer).toHaveFocus();
  expect(answer).toHaveAttribute("aria-selected", "true");
  expect(review).toHaveAttribute("tabindex", "-1");
});
