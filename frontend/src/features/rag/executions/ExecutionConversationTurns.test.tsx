import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ConversationDetail, ConversationTurn } from "../conversation/sessions-api";
import { ExecutionDetailPage } from "./ExecutionDetailPage";
import type { ExecutionDetail } from "./api";

const timestamp = "2026-10-27T00:00:00Z";
function turn(id: string, sequence: number, values: Partial<ConversationTurn> = {}): ConversationTurn {
  return { id, request_id: `request-${id}`, sequence, segment: 1, query: `합성 질문 ${sequence}`,
    status: "completed", response: null, error_code: null, redacted: false, execution_terminated: true,
    created_at: timestamp, updated_at: timestamp, request_scope: null, execution_id: `execution-${id}`, ...values };
}
function conversation(id = "conversation-one", turns = [turn("one", 1), turn("two", 2)]): ConversationDetail {
  return { id, title: "공개 합성 대화", title_origin: "auto", legacy_state: "active", revision: 2,
    created_at: timestamp, updated_at: timestamp, turns };
}
function execution(values: Partial<ExecutionDetail> = {}): ExecutionDetail {
  return { id: "execution-two", record_kind: "execution", kind: "conversation", query: "현재 실행 질문",
    status: "completed", answer_status: "answered", created_at: timestamp, document_count: 0,
    domain_id: "domain", domain_slug: "synthetic", conversation_id: "conversation-one", turn_id: "two",
    observation_complete: true, quality_status: "unreviewed", generation: { status: "answered", text: "합성 저장 답변", citations: [] },
    evidence: [], stages: [], ...values };
}
function pending<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
function serve(detail: ExecutionDetail, session: ConversationDetail) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) =>
    Response.json(String(input).includes("/conversations/") ? session : detail)));
}
afterEach(() => vi.unstubAllGlobals());

it("links only the same conversation executions with explicit order, segment and current selection", async () => {
  serve(execution(), conversation("conversation-one", [turn("two", 2, { segment: 2 }), turn("one", 1)]));
  render(<ExecutionDetailPage id="execution-two" />);
  const navigation = within(await screen.findByRole("navigation", { name: "같은 대화의 턴" }));
  const links = await navigation.findAllByRole("link");
  expect(links.map(link => link.getAttribute("href"))).toEqual([
    "/admin/rag/executions/execution-one", "/admin/rag/executions/execution-two",
  ]);
  expect(links[0]).toHaveTextContent("1번 질문 · 구간 1");
  expect(links[1]).toHaveTextContent("2번 질문 · 구간 2");
  expect(links[1]).toHaveTextContent("현재 실행");
  expect(links[1]).toHaveAttribute("aria-current", "page");
  expect(links[0]).not.toHaveAttribute("aria-current");
  links[0].focus();
  await userEvent.tab();
  expect(links[1]).toHaveFocus();
  expect(screen.getByText("합성 저장 답변")).toBeVisible();
});

it("keeps a current turn without an execution unlinked and never renders redacted question text", async () => {
  serve(execution(), conversation("conversation-one", [turn("one", 1, { redacted: true, query: "노출하면 안 되는 합성 질문" }),
    turn("two", 2, { execution_id: null }), turn("three", 3, { execution_id: null, status: "running" })]));
  render(<ExecutionDetailPage id="execution-two" />);
  const navigation = within(await screen.findByRole("navigation", { name: "같은 대화의 턴" }));
  expect(await navigation.findByText("현재 실행")).toBeVisible();
  expect(navigation.queryByRole("link")).not.toBeInTheDocument();
  expect(navigation.getAllByText("연결된 실행 기록 없음")).toHaveLength(2);
  expect(navigation.getByText("현재 권한으로 볼 수 없는 질문")).toBeVisible();
  expect(screen.queryByText("노출하면 안 되는 합성 질문")).not.toBeInTheDocument();
});

it("aborts old turn reads on route changes and ignores late previous conversation text", async () => {
  const oldSession = pending<Response>();
  let oldSignal: AbortSignal | null | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, options?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/conversation-one")) { oldSignal = options?.signal; return oldSession.promise; }
    if (path.endsWith("/conversation-two")) return Response.json(conversation("conversation-two", [turn("new", 1, { query: "새 대화 질문" })]));
    return Response.json(path.endsWith("/execution-new") ? execution({ id: "execution-new", turn_id: "new", conversation_id: "conversation-two" }) : execution());
  }));
  const view = render(<ExecutionDetailPage id="execution-two" />);
  await screen.findByText("대화 턴을 불러오고 있습니다…");
  view.rerender(<ExecutionDetailPage id="execution-new" />);
  expect(oldSignal?.aborted).toBe(true);
  await screen.findByText("새 대화 질문");
  await act(async () => oldSession.resolve(Response.json(conversation())));
  expect(screen.queryByText("합성 질문 1")).not.toBeInTheDocument();
  expect(screen.getByText("새 대화 질문")).toBeVisible();
});

it.each([403, 404])("clears prior turn text after refresh permission failure %s and supports retry", async status => {
  let allowed = true;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    if (!String(input).includes("/conversations/")) return Response.json(execution());
    return allowed ? Response.json(conversation()) : Response.json({}, { status });
  }));
  render(<ExecutionDetailPage id="execution-two" />);
  await screen.findByText("합성 질문 1");
  allowed = false;
  await userEvent.click(screen.getByRole("button", { name: "실행 상태 새로고침" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("합성 질문 1")).not.toBeInTheDocument();
  expect(screen.queryByText("합성 질문 2")).not.toBeInTheDocument();
  allowed = true;
  await userEvent.click(screen.getByRole("button", { name: "대화 턴 다시 조회" }));
  expect(await screen.findByText("합성 질문 1")).toBeVisible();
});

it("rejects a mismatched conversation response before showing its turns", async () => {
  serve(execution(), conversation("different-conversation"));
  render(<ExecutionDetailPage id="execution-two" />);
  expect(await screen.findByRole("alert")).toHaveTextContent("대화 턴을 열 수 없습니다");
  expect(screen.queryByText("합성 질문 1")).not.toBeInTheDocument();
});

it("does not infer a current turn when its saved identity is absent", async () => {
  serve(execution(), conversation("conversation-one", [turn("one", 1)]));
  render(<ExecutionDetailPage id="execution-two" />);
  const navigation = within(await screen.findByRole("navigation", { name: "같은 대화의 턴" }));
  expect(await navigation.findByText("현재 실행에 연결된 턴을 확인할 수 없습니다.")).toBeVisible();
  expect(navigation.queryByText("현재 실행")).not.toBeInTheDocument();
});

it("does not label a replacement execution on the same turn as the current execution", async () => {
  serve(execution(), conversation("conversation-one", [turn("two", 2, { execution_id: "replacement-execution" })]));
  render(<ExecutionDetailPage id="execution-two" />);
  const navigation = within(await screen.findByRole("navigation", { name: "같은 대화의 턴" }));
  const replacement = await navigation.findByRole("link");
  expect(replacement).toHaveAttribute("href", "/admin/rag/executions/replacement-execution");
  expect(replacement).not.toHaveAttribute("aria-current");
  expect(navigation.queryByText("현재 실행")).not.toBeInTheDocument();
  expect(navigation.getByText("현재 실행에 연결된 턴을 확인할 수 없습니다.")).toBeVisible();
});

it("shows an empty authorized conversation without inventing a turn", async () => {
  serve(execution(), conversation("conversation-one", []));
  render(<ExecutionDetailPage id="execution-two" />);
  const navigation = within(await screen.findByRole("navigation", { name: "같은 대화의 턴" }));
  expect(await navigation.findByText("표시할 대화 턴이 없습니다.")).toBeVisible();
  expect(navigation.queryByRole("link")).not.toBeInTheDocument();
});

it.each([{ kind: "evaluation" as const }, { record_kind: "legacy" as const }, { conversation_id: null }])(
  "does not label evaluation repetitions, legacy or unlinked records as conversation turns: %j", async values => {
    const detail = execution(values);
    serve(detail, conversation());
    render(<ExecutionDetailPage id={detail.id} kind={detail.record_kind} />);
    await screen.findByRole("heading", { level: 1, name: "현재 실행 질문" });
    expect(screen.queryByRole("navigation", { name: "같은 대화의 턴" })).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.every(([input]) => !String(input).includes("/conversations/"))).toBe(true);
  },
);
