import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { GenerativeEvaluationPanel } from "./GenerativeEvaluationPanel";
import * as api from "./generative-api";

vi.mock("./generative-api", () => ({
  listGenerativeRuns: vi.fn(), loadGenerativeRun: vi.fn(), listGenerativePolicies: vi.fn(),
  startGenerativeRun: vi.fn(), createGenerativePolicy: vi.fn(), reviewGenerativeAttempt: vi.fn(),
  loadAuthoringSnapshot: vi.fn(), retryGenerativeRun: vi.fn(), acceptGenerativeRun: vi.fn(),
}));

vi.mock("./EvaluationAuthoringPanel", () => ({
  EvaluationAuthoringPanel: ({ onInvalidate }: { onInvalidate: () => void }) => <button onClick={onInvalidate}>Edit draft</button>,
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


it("loads saved cases and resets stale rule input without creating data or running models", async () => {
  const saved = { id: "saved-snapshot", cases: [{ id: "saved-case", query: "saved synthetic question", expected_answer_status: "insufficient_evidence", expected_evidence_ids: [], expected_highlight: null }] } as api.AuthoringSnapshot;
  vi.mocked(api.loadAuthoringSnapshot).mockResolvedValue(saved);
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} />);
  fireEvent.click(screen.getByText("새 생성형 평가 준비"));
  fireEvent.change(screen.getByLabelText("저장된 평가 자료 ID"), { target: { value: "saved-snapshot" } });
  fireEvent.click(screen.getByRole("button", { name: "평가 자료 불러오기" }));
  expect(await screen.findByText("saved synthetic question")).toBeVisible();
  expect(api.loadAuthoringSnapshot).toHaveBeenCalledWith("saved-snapshot");
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("반드시 포함할 내용 (한 줄에 하나)"), "first{Enter}second");
  expect(screen.getByLabelText("반드시 포함할 내용 (한 줄에 하나)")).toHaveValue("first\nsecond");
  await user.type(screen.getByLabelText("포함하면 안 되는 내용 (한 줄에 하나)"), "bad{Enter}forbidden");
  expect(screen.getByLabelText("포함하면 안 되는 내용 (한 줄에 하나)")).toHaveValue("bad\nforbidden");
  expect(api.startGenerativeRun).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("반드시 포함할 내용 (한 줄에 하나)"), { target: { value: "stale rule" } });
  fireEvent.change(screen.getByLabelText("이전 질문 문맥 (선택, 원문 그대로 고정)"), { target: { value: "stale history" } });
  await waitFor(() => expect(screen.getByRole("button", { name: "평가 자료 불러오기" })).toBeEnabled());
  fireEvent.click(screen.getByRole("button", { name: "평가 자료 불러오기" }));
  await waitFor(() => expect(screen.getByLabelText("반드시 포함할 내용 (한 줄에 하나)")).toHaveValue(""));
  expect(screen.getByLabelText("이전 질문 문맥 (선택, 원문 그대로 고정)")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("검색 K"), { target: { value: "20" } });
  fireEvent.change(screen.getByLabelText("사례별 반복 횟수"), { target: { value: "3" } });
  expect(screen.getByLabelText("검색 K")).toHaveValue(20);
  expect(screen.getByLabelText("사례별 반복 횟수")).toHaveValue(3);
});


it("ignores an old snapshot response after editing the authoring draft", async () => {
  let resolve!: (snapshot: api.AuthoringSnapshot) => void;
  vi.mocked(api.loadAuthoringSnapshot).mockReturnValue(new Promise(value => { resolve = value; }));
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} />);
  fireEvent.click(screen.getByText("새 생성형 평가 준비"));
  fireEvent.change(screen.getByLabelText("저장된 평가 자료 ID"), { target: { value: "old-snapshot" } });
  fireEvent.click(screen.getByRole("button", { name: "평가 자료 불러오기" }));
  fireEvent.click(screen.getByRole("button", { name: "Edit draft" }));
  await act(async () => resolve({ id: "old-snapshot", cases: [{ id: "case-old", query: "obsolete saved question", expected_answer_status: "insufficient_evidence", expected_evidence_ids: [] }] }));
  expect(screen.queryByText("obsolete saved question")).not.toBeInTheDocument();
  expect(api.startGenerativeRun).not.toHaveBeenCalled();
});
