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
  expect(await screen.findByRole("heading", { name: "구성 config · v?" })).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: "근거·진단" }));
  expect(screen.getByRole("link", { name: "실행 단계 상세" })).toHaveAttribute("href", "/admin/rag/executions/execution-1");
  expect(api.loadGenerativeRun).toHaveBeenCalledWith("run-1", expect.any(AbortSignal));
  expect(api.startGenerativeRun).not.toHaveBeenCalled();
});

it("does not label valid citations as correct answers or missing timing as zero", async () => {
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} initialRunId="run-1" />);
  expect(await screen.findByText("정답: 미검증")).toBeVisible();
  expect(screen.getByText("인용: 유효")).toBeVisible();
  expect(screen.getByText("소요 시간: 시간 미기록")).toBeVisible();
  expect(screen.getByRole("heading", { name: "답변 비교 실험" })).toBeVisible();
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

it.each([
  ["completed", "insufficient_evidence", "근거 부족으로 답변하지 않았습니다."],
  ["pending", null, "실행 대기 중입니다."],
  ["running", null, "답변을 생성하고 있습니다."],
  ["failed", null, "실행에 실패해 답변을 저장하지 못했습니다."],
  ["interrupted", null, "실행이 중단되어 답변을 저장하지 못했습니다."],
])("distinguishes %s / %s from a missing stored answer", async (status, generationStatus, message) => {
  const attempt = { ...run.attempts[0], status, answer: null, observation: { ...run.attempts[0].observation!, generation_status: generationStatus } } as api.GenerativeRun["attempts"][number];
  vi.mocked(api.loadGenerativeRun).mockResolvedValue({ ...run, attempts: [attempt] });
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} initialRunId="run-1" />);
  expect(await screen.findByText(message)).toBeVisible();
  expect(screen.queryByText("저장된 생성 답변이 없습니다.")).not.toBeInTheDocument();
  if (generationStatus === "insufficient_evidence") expect(screen.getByText("결과: 근거 부족")).toBeVisible();
});

it("groups citations by exact revision, projection and page while preserving evidence counts", async () => {
  const source = { document_id: "doc", asset_version_id: "revision-1", projection_id: "projection-1", page: 2, title: "상품 설명서" };
  const sources = [
    { ...source, evidence_id: "e1" }, { ...source, evidence_id: "e2" },
    { ...source, evidence_id: "e3", asset_version_id: "revision-2" },
    { ...source, evidence_id: "e4", projection_id: "projection-2" },
    { ...source, evidence_id: "e5", page: 3 },
  ];
  vi.mocked(api.loadGenerativeRun).mockResolvedValue({ ...run, attempts: [{ ...run.attempts[0], sources }] });
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} initialRunId="run-1" />);
  fireEvent.click(await screen.findByRole("tab", { name: "근거·진단" }));
  expect(await screen.findByText("인용 근거 5건 · 원문 위치 4곳")).toBeVisible();
  expect(screen.getAllByRole("link", { name: /인용 원문/ })).toHaveLength(4);
  expect(screen.getByRole("link", { name: "상품 설명서 · 2쪽 인용 원문 · 근거 2건" })).toHaveAttribute("href", expect.stringContaining("revision-1"));
  const hrefs = screen.getAllByRole("link", { name: /인용 원문/ }).map(link => link.getAttribute("href"));
  expect(hrefs).toEqual(expect.arrayContaining([
    "/workshop/rag/sources/revision-1?projectionId=projection-1&page=2",
    "/workshop/rag/sources/revision-2?projectionId=projection-1&page=2",
    "/workshop/rag/sources/revision-1?projectionId=projection-2&page=2",
    "/workshop/rag/sources/revision-1?projectionId=projection-1&page=3",
  ]));
});

it("summarizes all attempt states and counts retries as attempts even when filtering a case", async () => {
  const statuses = ["completed", "completed", "running", "pending", "failed", "interrupted"];
  const attempts = statuses.map((status, index) => ({ ...run.attempts[0], id: `attempt-${index}`, status,
    case_id: index < 2 ? "case-1" : "case-2", attempt_number: index === 1 ? 2 : 1 }));
  vi.mocked(api.loadGenerativeRun).mockResolvedValue({ ...run, status: "running", attempts });
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} initialRunId="run-1" initialCaseId="case-1" />);
  expect(await screen.findByText("전체 시도 6건 · 완료 2건 · 진행 1건 · 대기 1건 · 실패 1건 · 중단 1건")).toBeVisible();
  expect(screen.getAllByRole("heading", { name: "구성 config · v?" })).toHaveLength(1);
  fireEvent.click(screen.getByText("이 반복의 이전 시도 1건"));
  expect(await screen.findByText("이 반복의 이전 시도 1건")).toBeVisible();
});

it.each(["failed", "interrupted"])("does not report unpreserved failure observations as zero retrieval coverage for %s", async status => {
  const attempt = { ...run.attempts[0], status, answer: null, error_code: "citation_validation_failed",
    observation: { ...run.attempts[0].observation!, retrieved_evidence_ids: [], selected_evidence_ids: [], error_code: "citation_validation_failed" },
    metrics: { ...run.attempts[0].metrics!, retrieval_coverage: 0, context_coverage: 0, generation_completed: false, citation_valid: null } };
  vi.mocked(api.loadGenerativeRun).mockResolvedValue({ ...run, attempts: [attempt] });
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} initialRunId="run-1" />);
  expect(await screen.findByText("인용: 실패")).toBeVisible();
  expect(screen.getByText("생성: 완료 여부 미확인")).toBeVisible();
  fireEvent.click(screen.getByRole("tab", { name: "근거·진단" }));
  expect(screen.getAllByText(/실패·중단으로 측정값 확인 불가/)).toHaveLength(2);
  expect(screen.queryByText(/0\.0%/)).not.toBeInTheDocument();
  expect(screen.getByText("실패·중단된 시도의 검색·문맥 측정값은 보존되지 않았을 수 있습니다. 실행 단계 상세에서 처리 단계와 오류를 확인하세요.")).toBeVisible();
});

it("finds questions without a case combo and compares the same repetition", async () => {
  const attempts = [0, 1].flatMap(repetition => ["config-a", "config-b"].map(configuration_version_id => ({ ...run.attempts[0], id: `${repetition}-${configuration_version_id}`, repetition, configuration_version_id, answer: `answer-${repetition}-${configuration_version_id}` })));
  attempts.push({ ...attempts[0], id: "other", case_id: "other", query: "다른 질문", answer: "other answer" });
  vi.mocked(api.loadGenerativeRun).mockResolvedValue({ ...run, attempts });
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} initialRunId="run-1" />);
  expect(await screen.findByRole("textbox", { name: "질문 검색" })).toBeVisible();
  expect(screen.queryByRole("combobox", { name: "평가 사례" })).not.toBeInTheDocument();
  expect(screen.getByText("answer-0-config-a")).toBeVisible();
  expect(screen.queryByText("answer-1-config-a")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "반복 2" }));
  expect(screen.getByText("answer-1-config-a")).toBeVisible();
  expect(screen.getByText("answer-1-config-b")).toBeVisible();
  fireEvent.change(screen.getByRole("textbox", { name: "질문 검색" }), { target: { value: "다른" } });
  fireEvent.click(screen.getByRole("button", { name: /다른 질문/ }));
  expect(screen.getByText("other answer")).toBeVisible();
  expect(window.location.search).not.toContain("다른");
  expect(screen.getByRole("button", { name: "질문 목록으로" })).toBeInTheDocument();
});

it("preserves the selected question on refresh and resets it when selecting another run", async () => {
  const first = { ...run, attempts: [run.attempts[0], { ...run.attempts[0], id: "second", case_id: "case-2", query: "두번째 질문", answer: "두번째 답변" }] };
  const other = { ...run, id: "run-2", created_at: "2026-09-29T00:00:00Z", attempts: [{ ...run.attempts[0], id: "third", case_id: "case-3", query: "새 실행 질문", answer: "새 답변" }] };
  vi.mocked(api.listGenerativeRuns).mockResolvedValue([first, other]);
  vi.mocked(api.loadGenerativeRun).mockImplementation(async id => id === "run-2" ? other : first);
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} initialRunId="run-1" initialCaseId="case-2" />);
  expect(await screen.findByText("두번째 답변")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "결과 새로고침" }));
  await waitFor(() => expect(screen.getByRole("button", { name: "결과 새로고침" })).toBeEnabled());
  expect(screen.getByText("두번째 답변")).toBeVisible();
  expect(window.location.search).toContain("case=case-2");
  fireEvent.click(screen.getByText("실행 이력 · 2건"));
  const history = screen.getAllByRole("button").find(button => button.textContent?.includes("2026. 9. 29."));
  expect(history).toBeDefined();
  fireEvent.click(history!);
  expect(await screen.findByText("새 답변")).toBeVisible();
  expect(window.location.search).toContain("case=case-3");
  expect(api.startGenerativeRun).not.toHaveBeenCalled();
});

it("keeps a newer question selection when an earlier refresh response arrives", async () => {
  const selectedRun = { ...run, attempts: [run.attempts[0], { ...run.attempts[0], id: "second", case_id: "case-2", query: "두번째 질문", answer: "두번째 답변" }] };
  let resolveRefresh!: (value: api.GenerativeRun) => void;
  vi.mocked(api.loadGenerativeRun).mockResolvedValueOnce(selectedRun).mockImplementationOnce(() => new Promise(resolve => { resolveRefresh = resolve; }));
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} initialRunId="run-1" />);
  expect(await screen.findByText("합성 답변")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "결과 새로고침" }));
  fireEvent.click(screen.getByRole("button", { name: /두번째 질문/ }));
  await act(async () => resolveRefresh(selectedRun));
  expect(screen.getByText("두번째 답변")).toBeVisible();
  expect(screen.queryByText("합성 답변")).not.toBeInTheDocument();
  expect(window.location.search).toContain("case=case-2");
});

it("keeps diagnostics and review unmounted on the answer tab and explicitly expands long answers", async () => {
  const answer = "긴 합성 답변입니다. ".repeat(50);
  vi.mocked(api.loadGenerativeRun).mockResolvedValue({ ...run, attempts: [{ ...run.attempts[0], answer }] });
  render(<GenerativeEvaluationPanel configurations={[]} workspaces={[]} initialRunId="run-1" />);
  const expand = await screen.findByRole("button", { name: "답변 전체 보기" });
  expect(expand).toHaveAttribute("aria-expanded", "false");
  expect(screen.queryByText("검색 근거 충족률")).not.toBeInTheDocument();
  expect(screen.queryByText("이 답변 검토")).not.toBeInTheDocument();
  fireEvent.click(expand);
  expect(screen.getByRole("button", { name: "답변 접기" })).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(screen.getByRole("tab", { name: "검토" }));
  expect(screen.getByText("이 답변 검토")).toBeVisible();
  expect(screen.queryByRole("button", { name: "답변 접기" })).not.toBeInTheDocument();
});
