import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { getExecutionDetail, type ExecutionDetail } from "../executions/api";
import { EvaluationExecutionDiagnostics } from "./EvaluationExecutionDiagnostics";

vi.mock("../executions/api", () => ({ getExecutionDetail: vi.fn() }));
const detail = {
  observation_complete: true,
  evidence: [],
  stages: [{ stage: "selection", state: "completed", duration_ms: 2000, selection: {
    candidate_count: 1, truncated: false, min_semantic_score: .8, min_keyword_coverage: .5,
    candidates: [{ document_id: "doc", asset_version_id: "rev", projection_id: "projection", chunk_id: "chunk", page: 2,
      reason: "below_threshold", semantic_score: .72, keyword_coverage: .4, dense_score: .91, dense_rank: 1,
      sparse_score: null, sparse_rank: null, fused_score: .02, fused_rank: 1 }],
  } }],
} as unknown as ExecutionDetail;

beforeEach(() => vi.mocked(getExecutionDetail).mockReset());
it("loads recorded scores only when opened and distinguishes cosine from coverage", async () => {
  vi.mocked(getExecutionDetail).mockResolvedValue(detail);
  render(<EvaluationExecutionDiagnostics executionId="run-1" />);
  expect(getExecutionDetail).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "유사도·근거 선택 보기" }));
  expect(await screen.findByText("0.7200")).toBeVisible();
  expect(screen.getByText("0.9100 / 1")).toBeVisible();
  expect(screen.getByText("미기록 / —")).toBeVisible();
  expect(screen.getByText("기준 점수 미달")).toBeVisible();
  expect(screen.getByText(/유사도는 정답률이 아닙니다/)).toBeVisible();
  expect(screen.getByRole("link", { name: /원문 보기/ })).toHaveAttribute("href", "/workshop/rag/sources/rev?projectionId=projection&page=2");
  expect(getExecutionDetail).toHaveBeenCalledWith("run-1", "execution", expect.any(AbortSignal));
});
it("hides stale observations when the selected attempt changes", async () => {
  let resolve!: (value: ExecutionDetail) => void;
  vi.mocked(getExecutionDetail).mockReturnValue(new Promise(r => { resolve = r; }));
  const view = render(<EvaluationExecutionDiagnostics executionId="old" />);
  await userEvent.click(screen.getByRole("button", { name: "유사도·근거 선택 보기" }));
  view.rerender(<EvaluationExecutionDiagnostics executionId="new" />);
  await act(async () => resolve(detail));
  expect(screen.queryByText("0.7200")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "유사도·근거 선택 보기" })).toHaveAttribute("aria-expanded", "false");
});
it("shows missing observations and permits a read-only retry after an error", async () => {
  vi.mocked(getExecutionDetail).mockRejectedValueOnce(new Error("denied")).mockResolvedValueOnce({ ...detail, stages: [] });
  render(<EvaluationExecutionDiagnostics executionId="run-1" />);
  await userEvent.click(screen.getByRole("button", { name: "유사도·근거 선택 보기" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("현재 원문 접근 권한");
  await userEvent.click(screen.getByRole("button", { name: "진단 다시 불러오기" }));
  expect(await screen.findByText("이 실행에는 검색 후보 점수가 기록되지 않았습니다.")).toBeVisible();
  expect(screen.queryByText("0.0000")).not.toBeInTheDocument();
});
it("does not request diagnostics without an execution identity", () => {
  render(<EvaluationExecutionDiagnostics executionId={null} />);
  expect(screen.getByText("실행 기록이 연결되면 유사도를 확인할 수 있습니다.")).toBeVisible();
  expect(getExecutionDetail).not.toHaveBeenCalled();
});
