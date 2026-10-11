import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExecutionStages } from "./ExecutionStages";
import { ExecutionListPage } from "./ExecutionListPage";
import { ExecutionDetailPage } from "./ExecutionDetailPage";
import { getExecutionDetail, searchExecutions, type ExecutionDetail, type Stage } from "./api";

vi.mock("./api", () => ({ searchExecutions: vi.fn(), getExecutionDetail: vi.fn() }));

function evidenceDetail(selectedCount?: number): ExecutionDetail {
  const stages: Stage[] = [
    { stage: "request", state: "completed" },
    { stage: "history", state: "skipped" },
    { stage: "contextualization", state: "skipped" },
    { stage: "retrieval", state: "completed" },
    { stage: "selection", state: "completed", ...(selectedCount == null ? {} : {
      selection: { candidate_count: 4, selected_count: selectedCount, truncated: false },
    }) },
    { stage: "generation", state: "completed" },
    { stage: "citation_validation", state: "failed" },
    { stage: "persistence", state: "completed" },
  ];
  return { id: "synthetic-evidence-execution", record_kind: "execution", kind: "evaluation",
    query: "합성 근거 기록 질문", status: "failed", answer_status: null,
    created_at: "2026-10-05T00:00:00Z", document_count: 1, domain_id: null, domain_slug: null,
    conversation_id: null, turn_id: null, observation_complete: true, quality_status: "unreviewed",
    generation: null, evidence: [], stages };
}

async function openRecordedEvidence(detail: ExecutionDetail, count: number) {
  vi.mocked(getExecutionDetail).mockResolvedValue(detail);
  render(<ExecutionDetailPage id={detail.id} />);
  const summary = await screen.findByText(`기록된 생성 근거 원문 (${count})`, { selector: "summary" });
  const disclosure = summary.closest("details");
  if (!disclosure) throw new Error("Recorded evidence disclosure is missing");
  expect(disclosure).not.toHaveAttribute("open");
  await userEvent.click(summary);
  return within(disclosure);
}

it("shows every actual exceeded constraint in the existing monitoring candidate card", async () => {
  const detail = evidenceDetail(0);
  const candidate = { document_id: "synthetic-document", asset_version_id: "synthetic-version",
    projection_id: "synthetic-projection", evidence_unit_id: "synthetic-unit", chunk_id: "synthetic-chunk",
    selected: false, reason: "budget_exceeded", budget_trace: {
      incoming_units: 5, incoming_characters: 120, before_groups: 2, before_units: 6,
      before_characters: 100, group_limit: 2, unit_limit: 8, character_limit: 200,
      violated: ["groups" as const, "units" as const, "characters" as const],
    } };
  detail.stages = [{ stage: "selection", state: "completed", selection: {
    candidate_count: 1, selected_count: 0, truncated: false, candidates: [candidate],
  } }];
  vi.mocked(getExecutionDetail).mockResolvedValue(detail);
  render(<ExecutionDetailPage id={detail.id} />);
  await userEvent.click(await screen.findByText("검색 근거·유사도·선택 사유", { selector: "summary" }));
  expect(screen.getByText("문맥 묶음 1개 / 남은 0개 (전체 한도 2개)")).toBeVisible();
  expect(screen.getByText("원문 단위 5개 / 남은 2개 (전체 한도 8개)")).toBeVisible();
  expect(screen.getByText("문자 120자 / 남은 100자 (전체 한도 200자)")).toBeVisible();
  expect(screen.getByText("입력 예산 초과")).toBeVisible();
});

it("separates selected evidence from missing recorded sources after validation failure", async () => {
  const recorded = await openRecordedEvidence(evidenceDetail(4), 0);
  expect(recorded.getByText("생성 요청에 선택된 근거: 4개.")).toBeVisible();
  expect(recorded.getByText("이 실행에서 표시할 수 있는 근거 원문 기록이 없습니다.")).toBeVisible();
  expect(recorded.queryByRole("button")).not.toBeInTheDocument();
  expect(screen.queryByText(/생성에 전달된 전체 근거/)).not.toBeInTheDocument();
  const stages = within(screen.getByRole("list", { name: "RAG 처리 단계" })).getAllByRole("listitem");
  expect(stages).toHaveLength(8);
  expect(stages[5]).toHaveAttribute("data-state", "completed");
  expect(stages[6]).toHaveAttribute("data-state", "failed");
});

it("shows unrecorded selection without inventing a zero selected count", async () => {
  const recorded = await openRecordedEvidence(evidenceDetail(), 0);
  expect(recorded.getByText("생성 요청에 선택된 근거: 미기록.")).toBeVisible();
  expect(recorded.queryByText("생성 요청에 선택된 근거: 0개.")).not.toBeInTheDocument();
  expect(recorded.queryByText("이 실행에서 표시할 수 있는 근거 원문 기록이 없습니다.")).not.toBeInTheDocument();
});

it("shows a true zero selection without implying lost source records", async () => {
  const detail = evidenceDetail(0);
  detail.status = "completed";
  detail.answer_status = "insufficient_evidence";
  detail.stages = detail.stages.map(stage => stage.stage === "generation" || stage.stage === "citation_validation"
    ? { ...stage, state: "skipped" } : stage);
  const recorded = await openRecordedEvidence(detail, 0);
  expect(recorded.getByText("생성 요청에 선택된 근거: 0개.")).toBeVisible();
  expect(recorded.queryByText("이 실행에서 표시할 수 있는 근거 원문 기록이 없습니다.")).not.toBeInTheDocument();
  expect(recorded.queryByText(/미기록/)).not.toBeInTheDocument();
});

it("counts recorded source buttons independently from selected evidence in a successful result", async () => {
  const detail = evidenceDetail(4);
  detail.status = "completed";
  detail.answer_status = "answered";
  detail.stages = detail.stages.map(stage => ({ ...stage, state: "completed" }));
  detail.generation = { status: "answered", text: "합성 답변", citations: [
    { claim_index: 0, evidence_ids: ["synthetic-evidence"] },
  ] };
  detail.evidence = [{ excerpt: "합성 원문", highlights: [], semantic_score: null,
    keyword_coverage: null, warnings: [], source: {
      asset_version_id: "synthetic-version", asset_version_number: 1, chunk_id: "synthetic-chunk",
      document_id: "synthetic-document", element_id: "synthetic-element", evidence_unit_id: "synthetic-evidence",
      folder_id: null, media_type: "application/pdf", projection_id: "synthetic-projection", section_path: [],
      title: "합성 문서", workspace_id: "synthetic-workspace", location: {
        bbox: null, char_start: 0, char_end: 5, element_id: "synthetic-element", image_sha256: null,
        page: 2, source_kind: "pdf_page", source_part: null, table_cell: null,
      },
    } }];
  const recorded = await openRecordedEvidence(detail, 1);
  expect(recorded.getByText("생성 요청에 선택된 근거: 4개.")).toBeVisible();
  expect(recorded.getAllByRole("button")).toHaveLength(1);
  expect(recorded.getByRole("button", { name: "합성 문서 · 2쪽 원문" })).toBeVisible();
  expect(screen.getByRole("button", { name: "[1] 합성 문서 · 2쪽 원문" })).toBeVisible();
  expect(screen.getByText("합성 답변")).toBeVisible();
  expect(recorded.queryByText("이 실행에서 표시할 수 있는 근거 원문 기록이 없습니다.")).not.toBeInTheDocument();
});

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
