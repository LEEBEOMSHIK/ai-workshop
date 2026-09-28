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
  fireEvent.click(screen.getByRole("button", { name: "실패" }));
  expect(screen.getByRole("button", { name: /질문 failure/ })).toBeVisible();
  expect(screen.queryByRole("button", { name: /질문 recovered/ })).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "근거 부족" }));
  expect(screen.getByRole("button", { name: /질문 abstain/ })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "검토 필요" }));
  expect(screen.getByRole("button", { name: /질문 review/ })).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "진행 중" }));
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
  fireEvent.click(screen.getByRole("button", { name: "실패" }));
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
  fireEvent.click(screen.getByRole("button", { name: "검토 필요" }));
  expect(screen.getByText("답변 a")).toBeVisible();
  rerender(<Harness attempts={[attempt("a"), attempts[1]]} initial="a" />);
  expect(await screen.findByText("답변 b")).toBeVisible();
  expect(screen.queryByText("답변 a")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /질문 b/ })).toHaveAttribute("aria-pressed", "true");
});
