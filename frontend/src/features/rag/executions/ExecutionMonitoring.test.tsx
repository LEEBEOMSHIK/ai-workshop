import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExecutionStages } from "./ExecutionStages";
import { ExecutionListPage } from "./ExecutionListPage";
import { searchExecutions } from "./api";

vi.mock("./api", () => ({ searchExecutions: vi.fn() }));

it("shows missing duration without zero and distinguishes skipped from unrecorded", () => {
  render(<ExecutionStages stages={[
    { stage: "retrieval", state: "unrecorded", duration_ms: null },
    { stage: "generation", state: "skipped", duration_ms: null },
  ]} />);
  expect(screen.getByText("미기록")).toBeVisible();
  expect(screen.getByText("생략")).toBeVisible();
  expect(screen.queryByText("0.00초")).not.toBeInTheDocument();
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
