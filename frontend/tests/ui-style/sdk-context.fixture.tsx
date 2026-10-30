import { useState } from "react";
import { createRoot } from "react-dom/client";
import { ExecutionDetailPage } from "../../src/features/rag/executions/ExecutionDetailPage";
import type { ExecutionDetail, Stage } from "../../src/features/rag/executions/api";
import type { ConversationDetail } from "../../src/features/rag/conversation/sessions-api";
import "../../src/app/styles.css";

const timestamp = "2026-10-27T00:00:00Z";
const params = new URLSearchParams(location.search);
const mode = params.get("mode") ?? "recorded";
const current = Number(location.pathname.match(/synthetic-execution-(\d+)/)?.[1] ?? 7);
const executionId = `synthetic-execution-${current}`;
const longQuestion = "공개 합성 자료에서 이전 대화와 검색 범위가 이어지는 조건을 설명하고 긴한글식별자가좁은화면에서페이지전체를넘치지않는지확인해주세요";
const turns = Array.from({ length: 16 }, (_, index) => ({
  id: `synthetic-turn-${index + 1}`, request_id: `synthetic-request-${index + 1}`, sequence: index + 1,
  segment: index < 4 ? 1 : 2, query: `${index + 1}. ${longQuestion}`, status: "completed" as const,
  response: null, error_code: null, redacted: index === 2, execution_terminated: true,
  created_at: timestamp, updated_at: timestamp, request_scope: null,
  execution_id: index === 3 ? null : `synthetic-execution-${index + 1}`,
}));
const conversation: ConversationDetail = { id: "synthetic-conversation", title: "공개 합성 턴 탐색",
  title_origin: "auto", legacy_state: "active", revision: 16, created_at: timestamp, updated_at: timestamp,
  turns: mode === "empty" ? [] : turns };
const body = (text: string) => ({ content_status: "complete" as const, text, characters: text.length, sha256: "abcdef0123456789".repeat(4) });
const stages: Stage[] = [
  { stage: "request", state: "completed", duration_ms: 20, history_selection: {
    max_history_messages: 4, max_history_tokens: 100, input_message_count: 6, selected_message_count: 2,
    messages: Array.from({ length: 6 }, (_, position) => ({ position,
      conversation_turn_id: position === 5 ? null : `10000000-0000-4000-8000-00000000000${Math.floor(position / 2) + 1}`,
      role: position % 2 === 0 ? "user" : "assistant", selected: position >= 4,
      reason: position < 2 ? "message_limit" : position === 2 ? "older_than_token_limit" : position === 3 ? "token_limit" : "selected" })),
  } },
  { stage: "contextualization", state: "completed", duration_ms: 250, contextualization: {
    content_retention: mode === "metadata" ? "metadata_only" : "retained", input_kind: "http_request",
    instructions: body("공개 합성 지침: 현재 질문을 이전 메시지에 맞게 재작성합니다. 내부 추론을 기록하지 않습니다."),
    input: body(JSON.stringify({ messages: [
      { role: "system", content: "공개 합성 문맥화 지침" },
      { role: "user", content: longQuestion },
    ], temperature: 0 }, null, 2)),
    output: mode === "omitted" ? { content_status: "omitted_validation_failure", characters: 42, sha256: "b".repeat(64) }
      : body(JSON.stringify({ resolved_query: "동일 구간에서 현재 권한과 유효한 답변 서명을 확인한 이전 메시지 중 최종 문맥 정책으로 채택된 입력을 설명합니다." })),
    observation_complete: mode !== "omitted", truncated: false,
  } },
  { stage: "retrieval", state: "completed", duration_ms: 45 },
  { stage: "generation", state: "completed", duration_ms: 750 },
];
const detail: ExecutionDetail = { id: executionId, record_kind: mode === "legacy" ? "legacy" : "execution",
  kind: mode === "evaluation" ? "evaluation" : "conversation", query: `${current}. ${longQuestion}`,
  status: "completed", answer_status: "answered", quality_status: "unreviewed", created_at: timestamp,
  document_count: 0, domain_id: "synthetic-domain", domain_slug: "synthetic", conversation_id: "synthetic-conversation",
  turn_id: `synthetic-turn-${current}`, observation_complete: true, duration_ms: 1065,
  generation: { status: "answered", text: "공개 합성 저장 답변입니다. 문맥에 채택된 메시지 수와 답변 품질 판정은 서로 다릅니다.", citations: [] },
  evidence: [], stages: mode === "legacy" ? [] : stages,
};

// Fetch is entirely local; the preview server also blocks every /api request.
globalThis.fetch = async (input, init) => {
  const method = (init?.method ?? (input instanceof Request ? input.method : "GET")).toUpperCase();
  const path = new URL(input instanceof Request ? input.url : String(input), location.origin).pathname;
  const denied = () => Response.json({ error: { code: "synthetic_only", message: "합성 미리보기 요청 제한", correlation_id: "synthetic" } }, { status: 403 });
  if (method !== "GET") return denied();
  if (path.includes("/conversations/")) return mode === "error" ? denied() : Response.json(conversation);
  if (path.startsWith("/api/v1/admin/rag/executions/")) return Response.json(detail);
  return denied();
};

function inspection() {
  const controls = [...document.querySelectorAll<HTMLElement>("main a,main button,main summary")]
    .filter(node => node.checkVisibility())
    .map(node => ({ label: node.textContent?.trim().slice(0, 70), height: node.getBoundingClientRect().height,
      width: node.getBoundingClientRect().width, focusVisible: node.matches(":focus-visible"),
      outline: getComputedStyle(node).outline, current: node.getAttribute("aria-current") }));
  const navigation = document.querySelector('nav[aria-label="같은 대화의 턴"] ol');
  return { synthetic: true, backendCalls: 0, viewport: innerWidth, documentWidth: document.documentElement.scrollWidth,
    navigation: navigation ? { height: navigation.getBoundingClientRect().height, clientHeight: navigation.clientHeight,
      scrollHeight: navigation.scrollHeight, overflowY: getComputedStyle(navigation).overflowY } : null, controls };
}
function Frame() {
  const [report, setReport] = useState("");
  return <><aside style={{ padding: ".5rem", background: "var(--color-surface)" }}>
    <p>공개 합성 미리보기 · 실제 API·모델 호출 0</p>
    <button type="button" onClick={() => setReport(JSON.stringify(inspection(), null, 2))}>레이아웃 측정</button>
    {report ? <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{report}</pre> : null}
  </aside><ExecutionDetailPage id={executionId} kind={detail.record_kind} /></>;
}
function Preview() {
  if (window.parent !== window || params.get("frame") === "1") return <Frame />;
  return <main style={{ padding: "1rem" }}><h1>SDK 문맥 합성 화면 검토</h1>
    <p>각 프레임은 실제 컴포넌트/CSS를 사용합니다. 링크는 합성 실행 상세로만 연결합니다.</p>
    <p>{["recorded", "empty", "error", "legacy", "evaluation", "metadata", "omitted"].map(value => <a key={value} href={`?mode=${value}`} style={{ display: "inline-block", padding: ".75rem" }}>{value}</a>)}</p>
    <div style={{ display: "flex", flexWrap: "wrap", alignItems: "start", gap: "1rem" }}>
      {[320, 375, 1000].map(width => <section key={width}><h2>{width}px</h2>
        <iframe title={`합성 실행 ${width}px`} src={`?frame=1&mode=${mode}`} width={width} height={1000} style={{ border: "1px solid var(--color-border)" }} />
      </section>)}
    </div>
  </main>;
}
createRoot(document.getElementById("root")!).render(<Preview />);
