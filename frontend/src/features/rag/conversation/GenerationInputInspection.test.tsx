import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { GenerationInputInspection, type GenerationInput } from "./GenerationInputInspection";
import { SearchDiagnostics } from "./SearchDiagnostics";

const sourceText = "공휴일은 지급일 계산에서 제외합니다.";
const requestJson = JSON.stringify({ messages: [
  { role: "system", content: "주어진 근거와 조건만 사용하세요." },
  { role: "user", content: JSON.stringify({ question: "언제 받나요?", resolved_query: "합성 상품 지급일",
    history: [], evidence: [{ evidence_id: "evidence-1", text: sourceText, group_ref: 0 }],
    evidence_groups: [{ group_id: "group-1", page: 2, section_path: ["지급 조건"], source_kind: "pdf" }],
  }) },
], temperature: 0, max_tokens: 128, response_format: { type: "json_object" } });

function capture(overrides: Partial<GenerationInput> = {}): GenerationInput {
  return { status: "response_received", provider: "openai_compatible", dialect: "chat_completions",
    model: "합성 등록 모델", model_version: 3, prompt_ref: "rag-answer-v3", profile_version: 2,
    request_json: requestJson, body_characters: requestJson.length,
    body_bytes: new TextEncoder().encode(requestJson).length, sha256: "a".repeat(64),
    content_status: "complete", capture_limit_characters: 100000, max_output_tokens: 128,
    evidence_budget: { max_groups: 8, max_units: 32, max_characters: 12000 },
    provider_truncation: "unknown", ...overrides };
}

async function open(input?: GenerationInput | null) {
  const result = render(<GenerationInputInspection input={input} />);
  await userEvent.setup().click(screen.getByText("LLM 입력 확인"));
  return result;
}

it("shows captured final instructions, questions, source text, citation IDs and exact JSON", async () => {
  await open(capture());
  expect(screen.getByText("HTTP 응답 수신 확인")).toBeVisible();
  expect(screen.getByText(/모델 내부에서 읽거나 이해했는지는 확인할 수 없습니다/)).toBeVisible();
  expect(screen.getByText("언제 받나요?")).toBeVisible();
  expect(screen.getByText("합성 상품 지급일")).toBeVisible();
  expect(screen.getByText(sourceText)).toBeVisible();
  expect(screen.getByText("evidence-1")).toBeVisible();
  expect(screen.getByText(/페이지: 2/)).toBeVisible();
  expect(screen.getByText("섹션: 지급 조건")).toBeVisible();
  expect(screen.getByText(/8개 묶음 · 32개 근거 단위 · 12000자/)).toBeVisible();
  await userEvent.click(screen.getByText("최종 지침과 메시지"));
  expect(screen.getByText("주어진 근거와 조건만 사용하세요.")).toBeVisible();
  expect(screen.getByText(/등록 모델: 합성 등록 모델 · 모델 버전: 3/)).toBeVisible();
  expect(screen.getByText(/전체 HTTP 본문 해시나 독립적인 네트워크 전송 증명은 아닙니다/)).toBeVisible();
  await userEvent.click(screen.getByText("전송 입력 JSON (허용 필드)"));
  expect(screen.getByLabelText("전송 입력 JSON 허용 필드").textContent).toBe(requestJson);
});

it("does not claim a prepared body was sent", async () => {
  await open(capture({ status: "prepared" }));
  expect(screen.getByText("전송 전 준비 입력 · 전송 확인 안 됨")).toBeVisible();
  expect(screen.queryByText("HTTP 응답 수신 확인")).not.toBeInTheDocument();
});

it.each([undefined, null])("explains absent historical or unsupported capture: %s", async (input) => {
  await open(input);
  expect(screen.getByText(/이 결과에는 최종 요청 본문 기록이 없습니다/)).toBeVisible();
  expect(screen.queryByText("전송 입력 JSON (허용 필드)")).not.toBeInTheDocument();
});

it("separates capture size omission from provider truncation", async () => {
  await open(capture({ content_status: "omitted_size_limit", request_json: null }));
  expect(screen.getByText(/표시용 기록 한도를 넘어 본문을 보관하지 않았습니다/)).toBeVisible();
  expect(screen.getByText(/실제 요청이 잘렸다는 뜻은 아닙니다/)).toBeVisible();
  expect(screen.getByText(/제공자 내부 입력 잘림: 확인 불가/)).toBeVisible();
  expect(screen.queryByText("전송 입력 JSON (허용 필드)")).not.toBeInTheDocument();
});

it.each(["{broken", JSON.stringify({ messages: [{ role: "user", content: "bad-json" }] })])(
  "keeps malformed bodies available without inventing parsed evidence", async (body) => {
    await open(capture({ request_json: body }));
    expect(screen.getByRole("status")).toHaveTextContent("입력 형식을 해석할 수 없습니다");
    await userEvent.click(screen.getByText("전송 입력 JSON (허용 필드)"));
    expect(screen.getByLabelText("전송 입력 JSON 허용 필드").textContent).toBe(body);
    expect(screen.queryByRole("table", { name: "최종 입력 근거" })).not.toBeInTheDocument();
  },
);

it("renders document markup as text without active HTML", async () => {
  const unsafe = '<img src=x onerror="alert(1)"><script>alert(1)</script>';
  // Build nested JSON normally so this test exercises valid source content, not parse failure.
  const parsed = JSON.parse(requestJson);
  const content = JSON.parse(parsed.messages[1].content);
  content.evidence[0].text = unsafe;
  parsed.messages[1].content = JSON.stringify(content);
  const { container } = await open(capture({ request_json: JSON.stringify(parsed) }));
  expect(within(screen.getByRole("table", { name: "최종 입력 근거" })).getByText(unsafe)).toBeVisible();
  expect(container.querySelector("img, script")).toBeNull();
});

it("shows empty evidence without claiming document conditions were preserved", async () => {
  const body = JSON.stringify({ messages: [{ role: "user", content: JSON.stringify({
    question: "합성 질문", resolved_query: "합성 질문", evidence: [], history: [],
  }) }] });
  await open(capture({ request_json: body, evidence_budget: null }));
  expect(screen.getByText("최종 입력에 근거가 없습니다.")).toBeVisible();
  expect(screen.getByText("근거 문맥 예산: 미설정")).toBeVisible();
});

it("rejects an invalid group reference rather than attaching another source's metadata", async () => {
  const body = JSON.parse(requestJson);
  const payload = JSON.parse(body.messages[1].content);
  payload.evidence[0].group_ref = -1;
  body.messages[1].content = JSON.stringify(payload);
  await open(capture({ request_json: JSON.stringify(body) }));
  expect(screen.getByRole("status")).toHaveTextContent("입력 형식을 해석할 수 없습니다");
  expect(screen.queryByRole("table", { name: "최종 입력 근거" })).not.toBeInTheDocument();
});

it("shows a missing complete body as unavailable", async () => {
  await open(capture({ request_json: null }));
  expect(screen.getByRole("status")).toHaveTextContent("요청 본문을 확인할 수 없습니다");
});

it("is reachable in the existing diagnostics panel with focusable disclosure controls", async () => {
  render(<SearchDiagnostics query="합성 질문" diagnostics={{
    candidate_scope: "returned_hits", min_keyword_coverage: 0.5, min_semantic_score: 0.9,
    stages_ms: {}, candidates: [], generation_input: capture(),
  }} />);
  const user = userEvent.setup();
  await user.tab();
  expect(screen.getByText(/검색 근거·유사도/)).toHaveFocus();
  await user.click(screen.getByText(/검색 근거·유사도/));
  await user.tab();
  expect(screen.getByText("LLM 입력 확인")).toHaveFocus();
  await user.click(screen.getByText("LLM 입력 확인"));
  expect(screen.getByText(sourceText)).toBeVisible();
  expect(screen.getByText("자격 / 선택")).toBeVisible();
  expect(screen.queryByText("자격 / 전달")).not.toBeInTheDocument();
});
