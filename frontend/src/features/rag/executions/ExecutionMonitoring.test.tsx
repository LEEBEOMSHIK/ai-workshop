import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExecutionStages } from "./ExecutionStages";
import { ExecutionListPage } from "./ExecutionListPage";
import { ExecutionDetailPage } from "./ExecutionDetailPage";
import { getExecutionDetail, searchExecutions } from "./api";

vi.mock("./api", () => ({ searchExecutions: vi.fn(), getExecutionDetail: vi.fn() }));

it("shows missing duration without zero and distinguishes skipped from unrecorded", () => {
  render(<ExecutionStages stages={[
    { stage: "retrieval", state: "unrecorded", duration_ms: null },
    { stage: "generation", state: "skipped", duration_ms: null },
  ]} />);
  expect(screen.getByText("미기록")).toBeVisible();
  expect(screen.getByText("생략")).toBeVisible();
  expect(screen.queryByText("0.00초")).not.toBeInTheDocument();
});

it("keeps usage guidance collapsed until requested", async () => {
  vi.mocked(searchExecutions).mockResolvedValue({ items: [], total: 0, failed_count: 0,
    insufficient_count: 0, duration_count: 0, duration_missing: 0, median_ms: null,
    p95_ms: null, next_cursor: null });
  render(<ExecutionListPage />);
  await screen.findByText("조건에 맞는 실행 기록이 없습니다.");
  const summary = screen.getByText("사용 방법", { selector: "summary" });
  expect(summary.closest("details")).not.toHaveAttribute("open");
  await userEvent.click(summary);
  expect(summary.closest("details")).toHaveAttribute("open");
  expect(screen.getByText(/자동으로 새로고침되지 않습니다/)).toBeVisible();
});

it("opens retrieval diagnostics on demand while keeping the answer and stages visible", async () => {
  vi.mocked(getExecutionDetail).mockResolvedValue({ id: "test-execution", record_kind: "execution",
    kind: "conversation", query: "합성 질문", status: "completed", answer_status: "insufficient_evidence",
    created_at: "2026-09-30T00:00:00Z", document_count: 1, domain_id: null, domain_slug: null,
    conversation_id: null, turn_id: null, observation_complete: true, quality_status: "unreviewed",
    generation: null, evidence: [], stages: [{ stage: "retrieval", state: "completed", duration_ms: 1200 }] });
  render(<ExecutionDetailPage id="test-execution" />);
  const summary = await screen.findByText("검색 근거·유사도·선택 사유", { selector: "summary" });
  expect(screen.getByText("답변할 근거가 부족합니다.")).toBeVisible();
  expect(screen.getByRole("list", { name: "RAG 처리 단계" })).toBeVisible();
  expect(summary.closest("details")).not.toHaveAttribute("open");
  await userEvent.click(summary);
  expect(screen.getByText(/문맥 코사인과 검색 점수는 답변 정확도가 아닙니다/)).toBeVisible();
});

it("filters through POST data and shows global denominators", async () => {
  vi.mocked(searchExecutions).mockResolvedValue({ items: [], total: 7, failed_count: 2,
    insufficient_count: 3, duration_count: 4, duration_missing: 3, median_ms: 1500,
    p95_ms: 5000, next_cursor: null });
  render(<ExecutionListPage />);
  await waitFor(() => expect(screen.getByText(/측정 4건/)).toBeVisible());
  await userEvent.type(screen.getByLabelText("질문 검색"), "합성 질문");
  await userEvent.click(screen.getByRole("button", { name: "조회" }));
  await waitFor(() => expect(searchExecutions).toHaveBeenLastCalledWith(
    expect.objectContaining({ query: "합성 질문" }), expect.any(AbortSignal)));
  expect(window.location.href).not.toContain(encodeURIComponent("합성 질문"));
});
