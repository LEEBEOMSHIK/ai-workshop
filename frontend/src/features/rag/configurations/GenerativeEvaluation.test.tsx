import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { GenerativeEvaluationPanel } from "./GenerativeEvaluationPanel";
import * as api from "./generative-api";

vi.mock("./generative-api", () => ({
  listGenerativeRuns: vi.fn(), loadGenerativeRun: vi.fn(), listGenerativePolicies: vi.fn(),
  startGenerativeRun: vi.fn(), createGenerativePolicy: vi.fn(), reviewGenerativeAttempt: vi.fn(),
  retryGenerativeRun: vi.fn(), acceptGenerativeRun: vi.fn(),
}));

const run = {
  id: "run-1", kind: "generative", metric_version: "generative-v1", dataset_snapshot_id: "dataset",
  policy_id: "policy", rules_digest: "digest", status: "completed", created_at: "2026-09-28T00:00:00Z", repetition_count: 2,
  attempts: [{ id: "attempt-1", case_id: "case-1", configuration_version_id: "config", query: "합성 질문",
    repetition: 0, attempt_number: 1, status: "completed", execution_id: "execution-1", result_digest: "digest",
    answer: "합성 답변", sources: [], error_code: null,
    observation: { execution_id: "execution-1", generation_status: "answered", citation_valid: true,
      access_exposures: [], cited_evidence_ids: [], retrieved_evidence_ids: [], selected_evidence_ids: [] },
    metrics: { metric_version: "generative-v1", retrieval_coverage: 1, context_coverage: 1, required_group_count: 1,
      generation_completed: true, citation_valid: true, correctness: "unreviewed", abstention_correct: null, access_leaks: 0, duration_ms: null },
    judgment: null }],
} as api.GenerativeRun;

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.listGenerativeRuns).mockResolvedValue([run]);
  vi.mocked(api.loadGenerativeRun).mockResolvedValue(run);
  vi.mocked(api.listGenerativePolicies).mockResolvedValue([]);
});

it("opens the exact run/case from a deep link without starting another run", async () => {
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} initialRunId="run-1" initialCaseId="case-1" />);
  expect(await screen.findByRole("heading", { name: "합성 질문" })).toBeVisible();
  expect(screen.getByRole("link", { name: "실행 단계 상세" })).toHaveAttribute("href", "/admin/rag/executions/execution-1");
  expect(api.loadGenerativeRun).toHaveBeenCalledWith("run-1", expect.any(AbortSignal));
  expect(api.startGenerativeRun).not.toHaveBeenCalled();
});

it("does not label valid citations as correct answers or missing timing as zero", async () => {
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} initialRunId="run-1" />);
  expect(await screen.findByText("정답: 미검증")).toBeVisible();
  expect(screen.getByText("인용: 유효")).toBeVisible();
  expect(screen.getByText("시간 미기록")).toBeVisible();
  expect(screen.getByText(/generative-v1/)).toBeVisible();
});
