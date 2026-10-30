import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ExecutionDetailPage } from "./ExecutionDetailPage";
import { getExecutionDetail, type ExecutionDetail } from "./api";
import { syntheticAgentTrace, syntheticContent } from "./agent-trace.test-support";

vi.mock("./api", () => ({ getExecutionDetail: vi.fn(), searchExecutions: vi.fn() }));
vi.mock("./mermaid-runtime", () => ({
  renderMermaid: vi.fn(async (_id: string, source: string) => ({
    svg: `<svg xmlns="http://www.w3.org/2000/svg">${Array.from(source.matchAll(/^n(\d+)\[/gm), ([, index]) =>
      `<g class="node" id="flowchart-n${index}-${index}" transform="translate(${100 + Number(index) * 120},100)"><rect width="80" height="40" /></g>`).join("")}${Array.from(source.matchAll(/\b(e\d+)@-->/g), ([, id]) => `<path id="${id}" />`).join("")}</svg>`,
  })),
}));

const originalGetBBox = Object.getOwnPropertyDescriptor(SVGElement.prototype, "getBBox");
beforeAll(() => {
  Object.defineProperty(SVGElement.prototype, "getBBox", { configurable: true,
    value: () => ({ x: -40, y: -20, width: 80, height: 40 }) });
});
afterAll(() => {
  if (originalGetBBox) Object.defineProperty(SVGElement.prototype, "getBBox", originalGetBBox);
  else Reflect.deleteProperty(SVGElement.prototype, "getBBox");
});

beforeEach(() => { vi.mocked(getExecutionDetail).mockReset(); });

function detail(id = "synthetic-execution"): ExecutionDetail {
  return { id, record_kind: "execution", kind: "conversation", query: `합성 질문 ${id}`,
    status: "running", answer_status: null, created_at: "2026-10-23T01:30:00Z", document_count: 0,
    domain_id: null, domain_slug: null, conversation_id: null, turn_id: null,
    observation_complete: true, quality_status: "unreviewed", generation: null,
    evidence: [], stages: [], agent_trace: syntheticAgentTrace(false) };
}

function retainedDetail(id = "synthetic-execution"): ExecutionDetail {
  const trace = syntheticAgentTrace();
  trace.spans[0] = { ...trace.spans[0], input: syntheticContent(`합성 저장 입력 ${id}`),
    output: syntheticContent("합성 관측 반환값") };
  return { ...detail(id), status: "completed", answer_status: "answered", quality_status: "failed",
    generation: { status: "answered", text: "합성 최종 답변", citations: [] }, agent_trace: trace };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

async function openRoot() {
  const diagram = within(screen.getByRole("region", { name: "에이전트 위임 그림" }));
  await userEvent.click(await diagram.findByRole("button", { name: "에이전트 · synthetic_manager · #1" }));
  return within(screen.getByRole("dialog", { name: "에이전트 · synthetic_manager" }));
}

async function openInput() {
  const dialog = await openRoot();
  await openTechnical();
  const input = within(dialog.getByRole("region", { name: "전달 입력" }));
  await userEvent.click(input.getByText("원문 펼치기", { selector: "summary" }));
}

async function openTechnical() {
  const dialog = within(screen.getByRole("dialog"));
  const summary = dialog.getByText("원문·기술 기록", { selector: "summary" });
  if (!summary.closest("details")!.open) await userEvent.click(summary);
  return within(summary.closest("details")!);
}

async function closeDetail() {
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "닫기" }));
}

it("opens recorded delegation relationships without reconstructing unretained bodies", async () => {
  vi.mocked(getExecutionDetail).mockResolvedValue(detail());
  render(<ExecutionDetailPage id="synthetic-execution" />);
  const panel = await screen.findByRole("region", { name: "에이전트 위임 흐름" });
  const diagram = within(panel).getByRole("region", { name: "에이전트 위임 그림" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await userEvent.click(await within(diagram).findByRole("button", { name: /위임.*synthetic_delegate/ }));
  const selected = screen.getByRole("dialog", { name: "위임 · synthetic_delegate" });
  expect(screen.queryByText("합성 위임 작업")).not.toBeInTheDocument();
  const technical = await openTechnical();
  expect(technical.getByText("synthetic_manager")).toBeVisible();
  expect(technical.getByText("synthetic_writer")).toBeVisible();
  expect(technical.getByText(/결과를 돌려받는 도구 위임/)).toBeVisible();
  expect(technical.getByRole("region", { name: "전달 입력" })).toHaveTextContent(/당시 본문 미보관/);
  expect(within(selected).queryByText("원문 펼치기")).not.toBeInTheDocument();
  expect(within(panel).getByText(/이 실행 이력에는 본문이 보관되지 않았습니다/)).toBeVisible();
  expect(screen.queryByText("합성 위임 작업")).not.toBeInTheDocument();
  await closeDetail();
  expect(within(screen.getByRole("region", { name: "실행 결과 요약" })).getByText("미검증")).toBeVisible();
});

it("reloads retained step bodies while preserving the question, final answer and quality result", async () => {
  const pending = deferred<ExecutionDetail>();
  vi.mocked(getExecutionDetail).mockResolvedValueOnce(retainedDetail()).mockReturnValueOnce(pending.promise);
  render(<ExecutionDetailPage id="synthetic-execution" />);
  await screen.findByRole("heading", { name: "합성 질문 synthetic-execution" });
  const openBodies = async () => {
    expect(screen.getByText("합성 최종 답변")).toBeVisible();
    expect(within(screen.getByRole("region", { name: "실행 결과 요약" })).getByText("실패")).toBeVisible();
    const selected = await openRoot();
    const technical = await openTechnical();
    for (const title of ["전달 지침", "전달 입력", "반환 결과"]) {
      await userEvent.click(within(technical.getByRole("region", { name: title })).getByText("원문 펼치기", { selector: "summary" }));
    }
    expect(selected.getByText("합성 역할 지침", { selector: "pre" })).toBeVisible();
    expect(selected.getByText("합성 저장 입력 synthetic-execution", { selector: "pre" })).toBeVisible();
    expect(selected.getByText("합성 관측 반환값", { selector: "pre" })).toBeVisible();
  };
  await openBodies();
  await closeDetail();
  await userEvent.click(screen.getByRole("button", { name: "실행 상태 새로고침" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByText("합성 저장 입력 synthetic-execution")).not.toBeInTheDocument();
  expect(screen.queryByText("합성 관측 반환값")).not.toBeInTheDocument();
  await act(async () => { pending.resolve(retainedDetail()); await pending.promise; });
  expect(screen.getByRole("heading", { name: "합성 질문 synthetic-execution" })).toBeVisible();
  await openBodies();
});

it("keeps legacy records empty instead of inventing agent nodes", async () => {
  vi.mocked(getExecutionDetail).mockResolvedValue({ ...detail(), record_kind: "legacy", agent_trace: null });
  render(<ExecutionDetailPage id="synthetic-execution" kind="legacy" />);
  const panel = await screen.findByRole("region", { name: "에이전트 위임 흐름" });
  expect(within(panel).getByText(/위임 기록이 없는 실행/)).toBeVisible();
  expect(within(panel).queryByRole("button")).not.toBeInTheDocument();
});

it("hides the previous execution immediately while the next identity is loading", async () => {
  const pending = deferred<ExecutionDetail>();
  vi.mocked(getExecutionDetail).mockImplementation(id => id === "first" ? Promise.resolve(retainedDetail("first")) : pending.promise);
  const view = render(<ExecutionDetailPage id="first" />);
  await screen.findByRole("heading", { name: "합성 질문 first" });
  await openInput();
  expect(screen.getByText("합성 저장 입력 first", { selector: "pre" })).toBeVisible();
  view.rerender(<ExecutionDetailPage id="second" />);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByText("합성 질문 first")).not.toBeInTheDocument();
  expect(screen.queryByText("합성 저장 입력 first")).not.toBeInTheDocument();
  expect(screen.getByRole("status")).toHaveTextContent(/불러오고/);
  await act(async () => { pending.resolve(detail("second")); await pending.promise; });
  expect(screen.getByRole("heading", { name: "합성 질문 second" })).toBeVisible();
});

it("does not allow an aborted previous request to overwrite the selected execution", async () => {
  const first = deferred<ExecutionDetail>();
  vi.mocked(getExecutionDetail).mockImplementation(id => id === "first" ? first.promise : Promise.resolve(detail("second")));
  const view = render(<ExecutionDetailPage id="first" />);
  view.rerender(<ExecutionDetailPage id="second" />);
  await screen.findByRole("heading", { name: "합성 질문 second" });
  await act(async () => { first.resolve(detail("first")); await first.promise; });
  expect(screen.queryByText("합성 질문 first")).not.toBeInTheDocument();
  expect(screen.getByRole("heading", { name: "합성 질문 second" })).toBeVisible();
});

it("revalidates access on refresh and hides the old trace if access is rejected", async () => {
  const pending = deferred<ExecutionDetail>();
  vi.mocked(getExecutionDetail).mockResolvedValueOnce(retainedDetail()).mockReturnValueOnce(pending.promise);
  render(<ExecutionDetailPage id="synthetic-execution" />);
  await screen.findByRole("heading", { name: "합성 질문 synthetic-execution" });
  await openInput();
  expect(screen.getByText("합성 저장 입력 synthetic-execution", { selector: "pre" })).toBeVisible();
  expect(screen.getByText(/자동으로 갱신되지/)).toBeVisible();
  await closeDetail();
  await userEvent.click(screen.getByRole("button", { name: "실행 상태 새로고침" }));
  expect(screen.queryByText("합성 질문 synthetic-execution")).not.toBeInTheDocument();
  expect(screen.queryByText("합성 저장 입력 synthetic-execution")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "실행 상태 새로고침" })).toBeDisabled();
  await act(async () => { pending.reject(new Error("forbidden")); await pending.promise.catch(() => undefined); });
  expect(screen.getByRole("alert")).toHaveTextContent(/접근 권한/);
  expect(screen.queryByRole("region", { name: "에이전트 위임 흐름" })).not.toBeInTheDocument();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.queryByText("합성 저장 입력 synthetic-execution")).not.toBeInTheDocument();
});

it("reports observation loss even if no agent trace was persisted", async () => {
  vi.mocked(getExecutionDetail).mockResolvedValue({ ...detail(), observation_complete: false, agent_trace: null });
  render(<ExecutionDetailPage id="synthetic-execution" />);
  expect(await screen.findByText("일부 관측 기록이 누락되었습니다.")).toBeVisible();
  expect(screen.getByText(/위임 기록이 없는 실행/)).toBeVisible();
});

it("does not expose a response bound to a different execution identity", async () => {
  vi.mocked(getExecutionDetail).mockResolvedValue(detail("other"));
  render(<ExecutionDetailPage id="synthetic-execution" />);
  expect(await screen.findByRole("alert")).toHaveTextContent(/열 수 없습니다/);
  expect(screen.queryByText("합성 질문 other")).not.toBeInTheDocument();
});

it.each([
  ["orchestration_budget_exceeded", "설정한 에이전트 실행 예산 초과"],
  ["orchestration_not_supported", "현재 모델/설정에서 SDK 실행 미지원"],
  ["orchestration_invalid_delegation", "위임 형식/대상 검증 실패"],
])("explains %s while retaining its diagnostic code", async (code, explanation) => {
  vi.mocked(getExecutionDetail).mockResolvedValue({ ...detail(), status: "failed", error_code: code });
  render(<ExecutionDetailPage id="synthetic-execution" />);
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(explanation);
  expect(within(alert).getByText(code, { selector: "code" })).toBeVisible();
});
