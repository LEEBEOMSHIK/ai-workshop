import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AgentSpanModal } from "./AgentSpanModal";
import { buildAgentFlow, type AgentSpan } from "./agent-flow";
import { syntheticAgentTrace, syntheticContent } from "./agent-trace.test-support";

const trace = syntheticAgentTrace();
const flow = buildAgentFlow(trace.spans);

function Harness({ span = trace.spans[0], showCompleteBody = true, openerRevision = "first", openerExists = true }: {
  span?: AgentSpan; showCompleteBody?: boolean; openerRevision?: string; openerExists?: boolean;
}) {
  const [open, setOpen] = useState(false);
  return <>
    <section aria-label="에이전트 위임 그림" tabIndex={-1}>
      {openerExists ? <button key={openerRevision} data-agent-span-id={span.id} onClick={() => setOpen(true)}>단계 열기</button> : null}
    </section>
    <button>배경 버튼</button>
    {open ? <AgentSpanModal span={span} parent={span.parent_id ? flow.byId.get(span.parent_id) : undefined}
      flow={flow} showCompleteBody={showCompleteBody} onClose={() => setOpen(false)} /> : null}
  </>;
}

it("starts with the question and observed answer while instructions and identifiers stay in purpose-specific disclosures", async () => {
  const span = { ...trace.spans[2], instructions: syntheticContent("Synthetic English rules that must remain exact."),
    input: syntheticContent(JSON.stringify({ question: "합성 핵심 질문", resolved_query: "합성 핵심 질문", available_evidence_count: 28,
      history: [{ role: "user", content: "합성 과거 질문" }], evidence: [{ text: "합성 근거 본문", evidence_id: "synthetic-hidden-id" }] })),
    output: syntheticContent('{"schema_version":2,"status":"answered","claims":[{"text":"합성 핵심 답변","evidence_ids":["synthetic-hidden-id"]}]}') };
  render(<Harness span={span} />);
  await userEvent.click(screen.getByRole("button", { name: "단계 열기" }));
  expect(within(screen.getByRole("region", { name: "받은 요청" })).getByText("합성 핵심 질문")).toBeVisible();
  expect(within(screen.getByRole("region", { name: "반환한 결과" })).getByText("합성 핵심 답변")).toBeVisible();
  expect(screen.getAllByText("합성 핵심 질문").filter(node => !node.closest("details"))).toHaveLength(1);
  for (const title of ["적용 지침", "함께 전달된 자료", "원문·기술 기록"]) {
    expect(screen.getByText(title, { selector: "summary" }).closest("details")).not.toHaveAttribute("open");
  }
  expect(screen.queryByText("Synthetic English rules that must remain exact.")).not.toBeInTheDocument();
  expect(screen.queryByText("synthetic-hidden-id", { exact: true })).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("적용 지침", { selector: "summary" }));
  expect(screen.getByText("Synthetic English rules that must remain exact.")).toBeVisible();
  await userEvent.click(screen.getByText("함께 전달된 자료", { selector: "summary" }));
  expect(screen.getByText("사용 가능한 근거 28개")).toBeVisible();
  expect(screen.getByText("입력에 기록된 근거 1개")).toBeVisible();
  expect(screen.getByText("사용자 (user)")).toBeVisible();
});

it("shows a model tool request as a request rather than an answer and reveals actual HTTP instructions on demand", async () => {
  const span = { ...trace.spans[4], instructions: { content_status: "not_applicable" as const, text: null, characters: null, sha256: null },
    input: syntheticContent(JSON.stringify({ messages: [{ role: "system", content: "Synthetic actual HTTP system rules" },
      { role: "user", content: '{"question":"합성 모델 질문","history":[],"available_evidence_count":28}' }], tools: [{ function: { name: "available_but_not_called" } }] })),
    output: syntheticContent('{"tool":"synthetic_tool","arguments":"{\\"task\\":\\"합성 도구 작업\\"}"}') };
  render(<Harness span={span} />);
  await userEvent.click(screen.getByRole("button", { name: "단계 열기" }));
  const result = within(screen.getByRole("region", { name: "반환한 결과" }));
  expect(result.getByText("도구 요청")).toBeVisible();
  expect(result.getByText("합성 도구 작업")).toBeVisible();
  expect(result.queryByText("답변 내용")).not.toBeInTheDocument();
  expect(screen.queryByText("Synthetic actual HTTP system rules")).not.toBeInTheDocument();
  await userEvent.click(screen.getByText("적용 지침", { selector: "summary" }));
  expect(screen.getByText("Synthetic actual HTTP system rules")).toBeVisible();
  expect(within(screen.getByText("적용 지침", { selector: "summary" }).closest("details")!).queryByText("해당 없음")).not.toBeInTheDocument();
  expect(screen.queryByText("입력에 기록된 근거 28개")).not.toBeInTheDocument();
});

it("keeps long multi-claim output as a limited preview with the entire original available", async () => {
  const longClaim = "합성 긴 주장 ".repeat(100);
  const original = JSON.stringify({ claims: [
    { text: longClaim }, { text: "둘째 합성 주장" }, { text: "셋째 합성 주장" }, { text: "넷째 합성 주장" },
  ] });
  render(<Harness span={{ ...trace.spans[2], output: syntheticContent(original) }} />);
  await userEvent.click(screen.getByRole("button", { name: "단계 열기" }));
  const result = within(screen.getByRole("region", { name: "반환한 결과" }));
  expect(result.queryByText("넷째 합성 주장")).not.toBeInTheDocument();
  expect(result.getByText(/앞부분 600자/)).toBeVisible();
  expect(result.getByText(/정리 표시 범위/)).toBeVisible();
  await userEvent.click(screen.getByText("원문·기술 기록", { selector: "summary" }));
  const full = within(screen.getByRole("region", { name: "반환 결과" }));
  await userEvent.click(full.getByText("원문 펼치기", { selector: "summary" }));
  expect(full.getByLabelText("반환 결과 원문").textContent).toBe(original);
});

it("opens the selected span with separate instructions, input and observed output", async () => {
  const span = { ...trace.spans[2], instructions: syntheticContent("합성 작성 지침"),
    input: syntheticContent('{"question":"합성 현재 질문"}'), output: syntheticContent('{"claims":[{"text":"합성 관측 출력","evidence_ids":[]}]}') };
  render(<Harness span={span} />);
  await userEvent.click(screen.getByRole("button", { name: "단계 열기" }));
  const dialog = within(screen.getByRole("dialog", { name: /에이전트.*synthetic_writer/ }));
  await userEvent.click(dialog.getByText("원문·기술 기록", { selector: "summary" }));
  expect(dialog.getByRole("region", { name: "전달 지침" })).toHaveTextContent("합성 작성 지침");
  expect(dialog.getByRole("region", { name: "전달 입력" })).toHaveTextContent("합성 현재 질문");
  expect(dialog.getByRole("region", { name: "반환 결과" })).toHaveTextContent("합성 관측 출력");
  expect(within(dialog.getByRole("region", { name: "반환 결과" })).getByText(/단계에서 관측한 반환값/)).toBeVisible();
  expect(dialog.getByLabelText("관측된 역할")).toHaveTextContent(/synthetic_manager.*synthetic_delegate.*위임 요청/);
});

it("traps Tab in the dialog and restores the opener and existing scroll style on Escape", async () => {
  document.body.style.overflow = "scroll";
  const user = userEvent.setup();
  render(<Harness />);
  const opener = screen.getByRole("button", { name: "단계 열기" });
  await user.click(opener);
  const dialog = screen.getByRole("dialog");
  const close = within(dialog).getByRole("button", { name: "닫기" });
  expect(close).toHaveFocus();
  expect(document.body.style.overflow).toBe("hidden");
  await user.tab({ shift: true });
  expect(within(dialog).getByRole("button", { name: "원문·기술 기록 도움말" })).toHaveFocus();
  await user.tab();
  expect(close).toHaveFocus();
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(opener).toHaveFocus();
  expect(document.body.style.overflow).toBe("scroll");
  document.body.style.overflow = "";
});

it("closes by button and backdrop, but never by clicking readable content", async () => {
  render(<Harness />);
  await userEvent.click(screen.getByRole("button", { name: "단계 열기" }));
  await userEvent.click(screen.getByText("합성 위임 작업"));
  expect(screen.getByRole("dialog")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "닫기" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "단계 열기" }));
  fireEvent.click(screen.getByRole("dialog").parentElement!);
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});

it("restores focus to a replacement node of the same ID, then to the diagram if the node disappeared", async () => {
  const user = userEvent.setup();
  const view = render(<Harness />);
  await user.click(screen.getByRole("button", { name: "단계 열기" }));
  view.rerender(<Harness openerRevision="replacement" />);
  await user.keyboard("{Escape}");
  expect(screen.getByRole("button", { name: "단계 열기" })).toHaveFocus();
  await user.click(screen.getByRole("button", { name: "단계 열기" }));
  view.rerender(<Harness openerRevision="replacement" openerExists={false} />);
  await user.keyboard("{Escape}");
  expect(screen.getByRole("region", { name: "에이전트 위임 그림" })).toHaveFocus();
});

it("does not leak denied content into the modal and keeps missing usage distinct from zero", async () => {
  const span = { ...trace.spans[4], instructions: syntheticContent("SECRET_INSTRUCTIONS"), input: syntheticContent("SECRET_INPUT"),
    output: { ...syntheticContent("SECRET_OUTPUT"), content_status: "omitted_validation_failure" as const }, input_tokens: 0, output_tokens: null };
  render(<Harness span={span} showCompleteBody={false} />);
  await userEvent.click(screen.getByRole("button", { name: "단계 열기" }));
  expect(document.body.textContent).not.toMatch(/SECRET_/);
  await userEvent.click(screen.getByText("원문·기술 기록", { selector: "summary" }));
  expect(document.body.textContent).not.toMatch(/SECRET_/);
  expect(screen.getByText("0 토큰")).toBeVisible();
  expect(screen.getByText("미보고")).toBeVisible();
  expect(within(screen.getByRole("region", { name: "반환 결과" })).getByText("답변 검증 실패로 본문 숨김")).toBeVisible();
});

it("replaces content by span ID when two different records have the same name", async () => {
  const first = { ...trace.spans[0], id: "first-record", name: "same_name", input: syntheticContent("FIRST_SYNTHETIC_INPUT") };
  const second = { ...first, id: "second-record", input: syntheticContent("SECOND_SYNTHETIC_INPUT") };
  const view = render(<Harness span={first} />);
  await userEvent.click(screen.getByRole("button", { name: "단계 열기" }));
  await userEvent.click(screen.getByText("원문·기술 기록", { selector: "summary" }));
  const input = within(screen.getByRole("region", { name: "전달 입력" }));
  await userEvent.click(input.getByText("원문 펼치기", { selector: "summary" }));
  expect(input.getByLabelText("전달 입력 원문")).toHaveTextContent("FIRST_SYNTHETIC_INPUT");
  view.rerender(<Harness span={second} />);
  expect(screen.getByText("SECOND_SYNTHETIC_INPUT")).toBeVisible();
  expect(document.body.textContent).not.toContain("FIRST_SYNTHETIC_INPUT");
  expect(screen.queryByLabelText("전달 입력 원문")).not.toBeInTheDocument();
});

it("keeps delegation state, source links and exact record ID without implying a successful handoff", async () => {
  const span = { ...trace.spans[1], state: "failed" as const, error_code: "synthetic_error",
    delegation_mode: "handoff" as const, evidence_refs: [{ document_id: "doc-synthetic", asset_version_id: "asset-synthetic", projection_id: "projection-synthetic" }] };
  render(<Harness span={span} />);
  await userEvent.click(screen.getByRole("button", { name: "단계 열기" }));
  expect(screen.getByText("실패", { exact: true })).toBeVisible();
  await userEvent.click(screen.getByText("원문·기술 기록", { selector: "summary" }));
  expect(screen.getByText(/제어권 인계.*handoff/)).toBeVisible();
  expect(screen.getByRole("alert")).toHaveTextContent("synthetic_error");
  await userEvent.click(screen.getByText("연결된 원문 (1)", { selector: "summary" }));
  expect(screen.getByRole("link", { name: "원문 1 열기" })).toHaveAttribute("href", expect.stringContaining("projectionId=projection-synthetic"));
  await userEvent.click(screen.getByText("단계 기록 정보", { selector: "summary" }));
  expect(screen.getByText("delegate", { exact: true })).toBeVisible();
  expect(screen.queryByText(/위임 완료|답변 완료/)).not.toBeInTheDocument();
});
