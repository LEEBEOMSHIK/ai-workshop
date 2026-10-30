import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { components } from "../../../shared/api/schema";
import { AgentStructuredContent } from "./AgentStructuredContent";
import { syntheticContent } from "./agent-trace.test-support";

type Content = components["schemas"]["AgentContent"];

function show(text: string) {
  return render(<AgentStructuredContent title="전달 입력" content={syntheticContent(text)} showCompleteBody />);
}

it("reads nested HTTP messages as roles, a question, conversation history and source evidence", () => {
  show(JSON.stringify({ messages: [
    { role: "system", content: "Synthetic grounding instructions" },
    { role: "user", content: JSON.stringify({ question: "합성 질문", resolved_query: "합성 독립 질의",
      history: [{ role: "user", content: "합성 이전 질문" }, { role: "assistant", content: "합성 이전 답변" }],
      evidence: [{ evidence_id: "synthetic-evidence", title: "합성 문서", text: "합성 근거 본문", page: 2 }],
      available_evidence_count: 0, delegated_task: "합성 위임 요청" }) },
  ], temperature: 0, stream: false }));
  expect(screen.getByText("메시지")).toBeVisible();
  expect(screen.getByText("시스템 (system)")).toBeVisible();
  expect(screen.getByText("질문")).toBeVisible();
  expect(screen.getByText("합성 질문")).toBeVisible();
  expect(screen.getByText("재작성 검색 질의")).toBeVisible();
  expect(screen.getByText("합성 독립 질의")).toBeVisible();
  expect(screen.getByText("대화 이력")).toBeVisible();
  expect(screen.getByText("합성 이전 답변")).toBeVisible();
  expect(screen.getByText("합성 근거 본문")).toBeVisible();
  expect(screen.getByText("합성 위임 요청")).toBeVisible();
});

it("shows claims and tool argument JSON without inventing a completed answer", () => {
  show(JSON.stringify({ tool: "synthetic_answer_tool", arguments: JSON.stringify({ task: "합성 작업" }),
    status: "answered", claims: [{ text: "합성 주장", evidence_ids: ["evidence-a", "evidence-b"] }] }));
  expect(screen.getByText("도구")).toBeVisible();
  expect(screen.getByText("synthetic_answer_tool")).toBeVisible();
  expect(screen.getByText("작업 요청")).toBeVisible();
  expect(screen.getByText("합성 작업")).toBeVisible();
  expect(screen.getByText("답변 주장")).toBeVisible();
  expect(screen.getByText("합성 주장")).toBeVisible();
  expect(screen.getByText("evidence-b")).toBeVisible();
});

it("reads compact evidence fragments inside actual HTTP message content without merging source references", () => {
  show(JSON.stringify({ messages: [{ role: "user", content: JSON.stringify({
    question: "합성 압축 근거 질문", evidence_sources: [{ page: 3, section_path: ["합성 절"] }],
    evidence_blocks: [{ source_ref: 0, fragments: [{ evidence_id: "fragment-a", text: "합성 압축 근거 본문" }] }],
  }) }] }));
  expect(screen.getByText("합성 절")).toBeVisible();
  expect(screen.getByText("근거 출처 참조")).toBeVisible();
  expect(screen.getByText("fragment-a")).toBeVisible();
  expect(screen.getByText("합성 압축 근거 본문")).toBeVisible();
});

it("preserves the exact original text behind a disclosure", async () => {
  const text = '{\n  "question": "합성 질문", "unexpected": {"stored": true}\n}\n';
  show(text);
  expect(screen.queryByLabelText("전달 입력 원문")).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("원문 펼치기", { selector: "summary" }));
  expect(screen.getByLabelText("전달 입력 원문").textContent).toBe(text);
  await userEvent.click(screen.getByText("기록 정보", { selector: "summary" }));
  expect(screen.getByText("a".repeat(64))).toBeVisible();
});

it.each([
  ["not_retained", "당시 본문 미보관"],
  ["disabled", "당시 본문 수집 안 함"],
  ["not_applicable", "해당 없음"],
  ["omitted_validation_failure", "답변 검증 실패로 본문 숨김"],
  ["omitted_size_limit", "크기 제한으로 본문 생략"],
] as const)("never mounts a body whose status is %s, even if the response includes text", (status, label) => {
  const content: Content = { ...syntheticContent('{"question":"SYNTHETIC_WITHHELD_BODY"}'), content_status: status };
  render(<AgentStructuredContent title="전달 입력" content={content} showCompleteBody />);
  expect(screen.getByText(label)).toBeVisible();
  expect(document.body.textContent).not.toContain("SYNTHETIC_WITHHELD_BODY");
  expect(screen.queryByText("원문 펼치기")).not.toBeInTheDocument();
});

it("withholds legacy complete content before rendering structured fields or raw text", () => {
  render(<AgentStructuredContent title="전달 입력" content={syntheticContent('{"question":"LEGACY_BODY"}')} showCompleteBody={false} />);
  expect(screen.getByText("당시 본문 미보관")).toBeVisible();
  expect(document.body.textContent).not.toContain("LEGACY_BODY");
  expect(screen.queryByText("원문 펼치기")).not.toBeInTheDocument();
});

it("removes an already opened original and readable text when retention access changes", async () => {
  const content = syntheticContent('{"question":"SYNTHETIC_REVOKED_BODY"}');
  const view = render(<AgentStructuredContent title="전달 입력" content={content} showCompleteBody />);
  await userEvent.click(screen.getByText("원문 펼치기", { selector: "summary" }));
  expect(screen.getByLabelText("전달 입력 원문")).toHaveTextContent("SYNTHETIC_REVOKED_BODY");
  view.rerender(<AgentStructuredContent title="전달 입력" content={content} showCompleteBody={false} />);
  expect(document.body.textContent).not.toContain("SYNTHETIC_REVOKED_BODY");
  expect(screen.queryByLabelText("전달 입력 원문")).not.toBeInTheDocument();
});

it.each([["", "빈 문자열로 기록되었습니다."], ["0", "0"], ["false", "false"], ["null", "null"]])(
  "distinguishes the recorded scalar %j from an absent body", (text, visible) => {
    show(text);
    expect(screen.getByText(visible, { exact: true })).toBeVisible();
    expect(screen.queryByText("본문 미기록")).not.toBeInTheDocument();
  },
);

it("keeps unknown JSON, hostile markup and field names as inert original text", async () => {
  const text = '{"__proto__":{"polluted":true},"<img src=x onerror=unsafe()>":"<script>unsafe()</script>"}';
  show(text);
  expect(screen.getByText(/알 수 없는 JSON/)).toBeVisible();
  await userEvent.click(screen.getByText("원문 펼치기", { selector: "summary" }));
  expect(screen.getByLabelText("전달 입력 원문").textContent).toBe(text);
  expect(document.querySelector("script, img")).toBeNull();
  expect(Object.prototype).not.toHaveProperty("polluted");
});

it("bounds deeply nested and long collections while retaining the full original", async () => {
  const history = Array.from({ length: 160 }, (_, index) => ({ role: "user", content: `합성 이력 ${index}` }));
  let nested: unknown = { question: "합성 가장 깊은 질문" };
  for (let index = 0; index < 50; index++) nested = { content: nested };
  const text = JSON.stringify({ history, content: nested });
  show(text);
  expect(screen.getByText(/나머지 .*항목은 원문/)).toBeVisible();
  expect(screen.getByText(/중첩이 깊은 내용/)).toBeVisible();
  expect(screen.queryByText("합성 이력 159", { exact: true })).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("원문 펼치기", { selector: "summary" }));
  expect(screen.getByLabelText("전달 입력 원문").textContent).toBe(text);
});

it("keeps a long plain text body complete and distinguishes absent content", () => {
  const text = "합성 장문 ".repeat(4000);
  const view = show(text);
  expect(within(screen.getByRole("region", { name: "전달 입력" })).getByText(text.trim()).textContent).toBe(text);
  view.rerender(<AgentStructuredContent title="전달 입력" showCompleteBody />);
  expect(screen.getByText("본문 미기록")).toBeVisible();
  expect(document.body.textContent).not.toContain(text);
});
