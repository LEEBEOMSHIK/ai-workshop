import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExecutionDetailPage } from "./ExecutionDetailPage";
import { getExecutionDetail, type ExecutionDetail, type Stage } from "./api";

vi.mock("./api", () => ({ getExecutionDetail: vi.fn() }));

function execution(stages: Stage[] = []): ExecutionDetail {
  return { id: "synthetic-context", record_kind: "execution", kind: "evaluation", query: "합성 문맥 질문",
    status: "completed", answer_status: "answered", created_at: "2026-10-27T00:00:00Z", document_count: 0,
    domain_id: null, domain_slug: null, conversation_id: null, turn_id: null,
    observation_complete: true, quality_status: "unreviewed", generation: null, evidence: [], stages };
}
const content = (text: string, content_status = "complete" as const) => ({ content_status, text, characters: text.length, sha256: "a".repeat(64) });
function contextualization() {
  return { content_retention: "retained" as const, input_kind: "http_request" as const,
    instructions: content("공개 합성 문맥화 지침"),
    input: content(JSON.stringify({ messages: [{ role: "user", content: "공개 합성 문맥화 HTTP 질문" }] })),
    output: content(JSON.stringify({ resolved_query: "공개 합성 재작성 질의" })), observation_complete: true, truncated: false };
}
async function openObservation(detail: ExecutionDetail) {
  vi.mocked(getExecutionDetail).mockResolvedValue(detail);
  render(<ExecutionDetailPage id={detail.id} kind={detail.record_kind} />);
  const summary = await screen.findByText("이전 대화 문맥·질문 문맥화", { selector: "summary" });
  expect(summary.closest("details")).not.toHaveAttribute("open");
  await userEvent.click(summary);
  return within(summary.closest("details")!);
}

it("shows actual selected messages, partial pairs and exclusion reasons without inventing turn links", async () => {
  const observed = { stage: "request" as const, state: "completed" as const, history_selection: {
    max_history_messages: 3, max_history_tokens: 25, input_message_count: 4, selected_message_count: 1,
    messages: [
      { position: 0, conversation_turn_id: "turn-one", role: "user" as const, selected: false, reason: "message_limit" as const },
      { position: 1, conversation_turn_id: "turn-one", role: "assistant" as const, selected: false, reason: "older_than_token_limit" as const },
      { position: 2, conversation_turn_id: "turn-two", role: "user" as const, selected: false, reason: "token_limit" as const },
      { position: 3, conversation_turn_id: null, role: "assistant" as const, selected: true, reason: "selected" as const },
    ] } };
  const panel = await openObservation(execution([observed]));
  expect(panel.getByText("준비된 입력 4개 메시지 · 실제 채택 1개 메시지")).toBeVisible();
  expect(panel.getByText(/최대 3개 메시지 · 25토큰/)).toBeVisible();
  expect(panel.getByText(/최종 문맥 정책에 전달된 최대 20개 메시지/)).toBeVisible();
  expect(panel.getByText(/준비 전 제외 내역은 포함하지 않습니다/)).toBeVisible();
  const rows = panel.getAllByRole("listitem");
  expect(rows).toHaveLength(4);
  expect(rows[0]).toHaveTextContent("메시지 1 · 사용자");
  expect(rows[0]).toHaveTextContent("메시지 수 제한으로 제외");
  expect(rows[1]).toHaveTextContent("더 최근 메시지에서 토큰 한도에 도달해 제외");
  expect(rows[2]).toHaveTextContent("토큰 제한으로 제외");
  expect(rows[3]).toHaveTextContent("메시지 4 · 어시스턴트");
  expect(rows[3]).toHaveTextContent("채택");
  expect(rows[3]).toHaveTextContent("출처 턴 미기록");
  expect(panel.queryByRole("link")).not.toBeInTheDocument();
});

it("reports old records as unrecorded without reconstructing a selection or HTTP request", async () => {
  const panel = await openObservation({ ...execution(), record_kind: "legacy" });
  expect(panel.getByText("이전 메시지 선택 미기록")).toBeVisible();
  expect(panel.getByText("질문 문맥화 본문 미기록")).toBeVisible();
  expect(panel.getByText(/과거 실행의 문맥 선택과 요청·응답을 복원하지 않습니다/)).toBeVisible();
  expect(panel.queryByText(/실제 채택 0개/)).not.toBeInTheDocument();
});

it("keeps empty observed history distinct from absent observations", async () => {
  const observed = { stage: "request" as const, state: "completed" as const, history_selection: {
    max_history_messages: 4, max_history_tokens: 100, input_message_count: 0, selected_message_count: 0, messages: [] } };
  const panel = await openObservation(execution([observed]));
  expect(panel.getByText("준비된 입력 0개 메시지 · 실제 채택 0개 메시지")).toBeVisible();
  expect(panel.getByText("준비된 이전 메시지가 없습니다.")).toBeVisible();
  expect(panel.queryByText("이전 메시지 선택 미기록")).not.toBeInTheDocument();
});

it("presents retained contextualization HTTP instructions, input and final output as a separate observed stage", async () => {
  const observed = { stage: "contextualization" as const, state: "completed" as const, contextualization: contextualization() };
  const panel = await openObservation(execution([observed]));
  expect(panel.getByText(/실제 HTTP 요청 본문/)).toBeVisible();
  expect(panel.getByText("공개 합성 문맥화 지침")).toBeVisible();
  expect(panel.getByText("공개 합성 문맥화 HTTP 질문")).toBeVisible();
  expect(panel.getByText("공개 합성 재작성 질의")).toBeVisible();
  const request = panel.getByRole("region", { name: "문맥화 HTTP 입력" });
  await userEvent.click(within(request).getByText("원문 펼치기", { selector: "summary" }));
  expect(within(request).getByLabelText("문맥화 HTTP 입력 원문")).toHaveTextContent('"messages"');
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("gates every contextualization body on retention even if metadata-only data contains text", async () => {
  const unsafe = content("노출 금지 합성 reasoning_content");
  const observed = { stage: "contextualization" as const, state: "completed" as const,
    contextualization: { ...contextualization(), content_retention: "metadata_only" as const,
      instructions: unsafe, input: unsafe, output: unsafe } };
  const panel = await openObservation(execution([observed]));
  expect(panel.getAllByText("당시 본문 미보관")).toHaveLength(3);
  expect(screen.queryByText(/노출 금지 합성/)).not.toBeInTheDocument();
  expect(panel.queryByText("원문 펼치기")).not.toBeInTheDocument();
});

it("shows omitted and incomplete body states without revealing text or treating a limit as truncated model input", async () => {
  const unavailable = { ...content("노출 금지 합성 비공개 추론"), content_status: "omitted_size_limit" as const };
  const observed = { stage: "contextualization" as const, state: "completed" as const,
    contextualization: { ...contextualization(), observation_complete: false, truncated: true,
      instructions: unavailable, input: unavailable, output: { ...unavailable, content_status: "omitted_validation_failure" as const } } };
  const panel = await openObservation(execution([observed]));
  expect(panel.getByText("문맥화 관측 기록이 불완전합니다.")).toBeVisible();
  expect(panel.getByText(/보관 한도로 일부 본문을 생략/)).toBeVisible();
  expect(panel.getAllByText("크기 제한으로 본문 생략")).toHaveLength(2);
  expect(panel.getByText("관측 본문 검증 실패로 본문 숨김")).toBeVisible();
  expect(panel.queryByText(/인용 또는 답변 검증/)).not.toBeInTheDocument();
  expect(screen.queryByText(/노출 금지 합성/)).not.toBeInTheDocument();
});

it("keeps skipped contextualization distinct from missing body capture", async () => {
  const panel = await openObservation(execution([{ stage: "contextualization", state: "skipped", reason: "history_empty" }]));
  expect(panel.getByText("이 실행에서는 질문 문맥화를 생략했습니다.")).toBeVisible();
  expect(panel.queryByText("문맥화 HTTP 입력")).not.toBeInTheDocument();
});

it("removes open private context bodies immediately on execution route changes", async () => {
  const first = execution([{ stage: "contextualization", state: "completed", ...{ contextualization: contextualization() } }]);
  vi.mocked(getExecutionDetail).mockResolvedValueOnce(first).mockImplementationOnce(() => new Promise(() => {}));
  const view = render(<ExecutionDetailPage id={first.id} />);
  await userEvent.click(await screen.findByText("이전 대화 문맥·질문 문맥화", { selector: "summary" }));
  expect(screen.getByText("공개 합성 문맥화 HTTP 질문")).toBeVisible();
  await act(async () => view.rerender(<ExecutionDetailPage id="other-execution" />));
  expect(screen.queryByText("공개 합성 문맥화 HTTP 질문")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent("실행 상세를 불러오고 있습니다");
});
