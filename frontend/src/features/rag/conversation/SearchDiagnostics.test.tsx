import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { SearchDiagnostics } from "./SearchDiagnostics";
import type { DomainSearchResult } from "./api";
import { syntheticAgentTrace } from "../executions/agent-trace.test-support";

vi.mock("../executions/mermaid-runtime", () => ({
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

async function openTechnical() {
  const summary = within(screen.getByRole("dialog")).getByText("원문·기술 기록", { selector: "summary" });
  if (!summary.closest("details")!.open) await userEvent.click(summary);
  return within(summary.closest("details")!);
}

it("shows actual request-local delegation input and distinguishes it from SDK input", async () => {
  render(<SearchDiagnostics query="합성 에이전트 질문" diagnostics={{
    candidate_scope: "returned_hits", min_keyword_coverage: 0.5, min_semantic_score: 0.9,
    stages_ms: {}, candidates: [], agent_trace: syntheticAgentTrace(),
  }} />);
  await userEvent.click(screen.getByText(/검색 근거·유사도.*에이전트 흐름/, { selector: "summary" }));
  const panel = screen.getByRole("region", { name: "에이전트 위임 흐름" });
  expect(within(panel).getByText(/현재 응답의 단계 기록/)).toBeVisible();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  const diagram = within(panel).getByRole("region", { name: "에이전트 위임 그림" });
  await userEvent.click(await within(diagram).findByRole("button", { name: "모델 호출 · synthetic_generation · #5" }));
  const selected = screen.getByRole("dialog", { name: "모델 호출 · synthetic_generation" });
  expect(selected.querySelector("script")).toBeNull();
  const technical = await openTechnical();
  expect(technical.getByText("HTTP 요청 본문")).toBeVisible();
  const input = within(technical.getByRole("region", { name: "전달 입력" }));
  expect(input.getByText(/SDK 실행 입력과 실제 HTTP 요청 본문은 서로 다를 수 있습니다/)).toBeVisible();
  await userEvent.click(input.getByText("원문 펼치기", { selector: "summary" }));
  expect(input.getByText(/합성 실제 요청 <script>unsafe\(\)<\/script>/, { selector: "pre" })).toBeVisible();
  expect(selected.querySelector("script")).toBeNull();
  expect(technical.getByText("0 토큰")).toBeVisible();
  expect(technical.getByText("12 토큰")).toBeVisible();
});

it("keeps validation-failed observed output hidden in current conversation diagnostics", async () => {
  const trace = syntheticAgentTrace();
  trace.spans[0] = { ...trace.spans[0], output: { content_status: "omitted_validation_failure",
    text: "합성 검증 실패 반환값", characters: 12, sha256: "b".repeat(64) } };
  render(<SearchDiagnostics query="합성 검증 실패 질문" diagnostics={{
    candidate_scope: "returned_hits", min_keyword_coverage: 0.5, min_semantic_score: 0.9,
    stages_ms: {}, candidates: [], agent_trace: trace,
  }} />);
  await userEvent.click(screen.getByText(/검색 근거·유사도.*에이전트 흐름/, { selector: "summary" }));
  const diagram = within(screen.getByRole("region", { name: "에이전트 위임 그림" }));
  await userEvent.click(await diagram.findByRole("button", { name: "에이전트 · synthetic_manager · #1" }));
  expect(screen.getByRole("dialog", { name: "에이전트 · synthetic_manager" })).toBeVisible();
  expect(screen.queryByText("합성 검증 실패 반환값")).not.toBeInTheDocument();
  const technical = await openTechnical();
  const output = technical.getByRole("region", { name: "반환 결과" });
  expect(within(output).getByText(/답변 검증 실패로 본문 숨김/)).toBeVisible();
  expect(screen.queryByText("합성 검증 실패 반환값")).not.toBeInTheDocument();
  expect(within(output).queryByText("원문 펼치기")).not.toBeInTheDocument();
  expect(output.querySelector("pre")).toBeNull();
});

it("shows admission-time budget counts only for document groups and distinguishes legacy and unchecked groups", async () => {
  const source = { document_id: "doc", asset_version_id: "asset", asset_version_number: 1,
    workspace_id: "space", folder_id: null, projection_id: "projection", chunk_id: "chunk",
    title: "synthetic.txt", media_type: "text/plain", section_path: [], fused_score: 0.02 };
  const candidate = { source, evidence_unit_id: null, sparse_score: null, dense_score: null,
    sparse_rank: null, dense_rank: null, fused_rank: 1, keyword_coverage: 0.7, semantic_score: 0.95,
    eligible: true, selected: false, reason: "budget_exceeded" };
  const traced = { ...candidate, budget_trace: {
    incoming_units: 33, incoming_characters: 712, before_groups: 1, before_units: 4,
    before_characters: 100, group_limit: 8, unit_limit: 32, character_limit: 12000,
    violated: ["units" as const],
  } };
  const diagnostics: NonNullable<DomainSearchResult["diagnostics"]> = {
    candidate_scope: "returned_hits", min_keyword_coverage: 0.5, min_semantic_score: 0.9,
    stages_ms: {}, candidates: [traced,
      { ...candidate, source: { ...source, chunk_id: "legacy" } },
      { ...candidate, source: { ...source, chunk_id: "unchecked" }, eligible: false, reason: "below_threshold" },
      { ...candidate, evidence_unit_id: "unit", reason: "below_threshold", eligible: false },
    ],
  };
  render(<SearchDiagnostics query="합성 질문" diagnostics={diagnostics} />);
  await userEvent.click(screen.getByText(/검색 근거·유사도/));
  expect(screen.getByText("원문 단위 33개 / 남은 28개 (전체 한도 32개)")).toBeVisible();
  expect(screen.getByText("세부 예산 미기록")).toBeVisible();
  expect(screen.getAllByText("예산 검사 전 제외")).toHaveLength(1);
  expect(screen.queryByText(/문자 712/)).not.toBeInTheDocument();
});

it("separates raw scores, cosine, missing values and stage times without claiming accuracy", async () => {
  render(<SearchDiagnostics query="resolved synthetic question" diagnostics={{
    candidate_scope: "returned_hits", min_keyword_coverage: 0.5, min_semantic_score: 0.9,
    stages_ms: { retrieval: 0, contextualization: null, total: 12 },
    candidates: [{
      source: { document_id: "doc", asset_version_id: "asset", asset_version_number: 1,
        workspace_id: "space", folder_id: null, projection_id: "projection", chunk_id: "chunk",
        title: "synthetic.txt", media_type: "text/plain", section_path: ["section"], fused_score: 0.02 },
      evidence_unit_id: null, sparse_score: 8.2, dense_score: null, sparse_rank: 1, dense_rank: null,
      fused_rank: 1, keyword_coverage: 0.4, semantic_score: 0.92,
      eligible: true, selected: true, reason: "selected",
    }],
  }} />);
  await userEvent.setup().click(screen.getByText(/검색 근거·유사도/));
  expect(screen.getByText("resolved synthetic question")).toBeVisible();
  expect(screen.getByText("문맥 코사인 유사도")).toBeVisible();
  expect(screen.getByText("8.2000")).toBeVisible();
  expect(screen.getAllByText("미계산").length).toBeGreaterThan(0);
  expect(screen.getByText("미실행")).toBeVisible();
  expect(screen.getByText("0.0 ms")).toBeVisible();
  expect(screen.queryByText(/정확도.*%/)).not.toBeInTheDocument();
});
