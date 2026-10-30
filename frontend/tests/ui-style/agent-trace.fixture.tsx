import { createRoot } from "react-dom/client";
import { useState } from "react";
import { AgentTracePanel } from "../../src/features/rag/executions/AgentTracePanel";
import { SearchDiagnostics } from "../../src/features/rag/conversation/SearchDiagnostics";
import { syntheticAgentTrace, syntheticBranchAgentTrace, syntheticContent, syntheticDeepAgentTrace, syntheticSteppedAgentTrace } from "../../src/features/rag/executions/agent-trace.test-support";
import { ExecutionStages } from "../../src/features/rag/executions/ExecutionStages";
import monitoring from "../../src/features/rag/executions/ExecutionMonitoring.module.css";
import "../../src/app/styles.css";

// Synthetic component and CSS harness. No authenticated app, live API or model is used.
function Fixture() {
  const [mode, setMode] = useState<"current" | "history" | "retained" | "empty" | "partial" | "branch" | "deep" | "steps">("current");
  const [narrow, setNarrow] = useState(false);
  const [panelWidth, setPanelWidth] = useState("auto");
  const trace = mode === "deep" ? syntheticDeepAgentTrace()
    : mode === "branch" ? syntheticBranchAgentTrace()
      : mode === "retained" ? syntheticSteppedAgentTrace()
        : mode === "steps" ? syntheticSteppedAgentTrace(false) : syntheticAgentTrace(mode === "current");
  trace.spans = trace.spans.map(span => span.id === "model" ? { ...span,
    model_name: `synthetic-model-${"긴모델식별자".repeat(10)}`,
    input: mode === "current" || mode === "retained" ? syntheticContent(JSON.stringify({
      messages: [{ role: "user", content: `합성 질문과 조건을 그대로 전달합니다. ${"긴한글문구와무공백영문식별자".repeat(14)}` }],
    })) : span.input,
  } : span);
  if (mode === "retained") {
    trace.spans = trace.spans.map(span => span.kind === "delegation" ? { ...span,
      instructions: { content_status: "not_applicable", text: null, characters: null, sha256: null },
    } : span);
  }
  if (mode === "history") {
    trace.spans[0] = { ...trace.spans[0],
      instructions: { content_status: "disabled", text: null, characters: null, sha256: null },
    };
  }
  if (mode === "partial") {
    trace.observation_complete = false;
    trace.truncated = true;
    trace.spans[0] = { ...trace.spans[0], state: "failed", error_code: "agent_model_call_limit", duration_ms: null };
  }
  return <div className="administration-area">
    <main className={monitoring.page}>
      <header><h1>합성 에이전트 모니터링 검증</h1><p>실제 SDK·모델 결과가 아닌 합성 UI 검사 자료입니다.</p></header>
      <nav aria-label="합성 검사 상태" style={{ display: "flex", flexWrap: "wrap", gap: ".5rem" }}>
        <button onClick={() => setMode("current")}>합성 현재 응답</button>
        <button onClick={() => setMode("history")}>합성 실행 이력</button>
        <button onClick={() => setMode("retained")}>합성 저장 본문</button>
        <button onClick={() => setMode("steps")}>합성 SDK 5단계</button>
        <button onClick={() => setMode("empty")}>합성 이전 기록</button>
        <button onClick={() => setMode("partial")}>합성 관측 누락</button>
        <button onClick={() => setMode("branch")}>합성 비정렬 분기</button>
        <button onClick={() => setMode("deep")}>합성 64단계 중첩</button>
        <button aria-pressed={narrow} onClick={() => setNarrow(value => !value)}>좁은 컨테이너</button>
        <label>모니터링 패널 폭<select value={panelWidth} onChange={event => setPanelWidth(event.target.value)} disabled={narrow}>
          <option value="auto">사용 가능한 전체 폭</option>
          <option value="1280">1280px</option><option value="375">375px</option><option value="320">320px</option>
        </select></label>
      </nav>
      <div style={{ minWidth: 0, maxWidth: narrow ? "560px" : panelWidth === "auto" ? "100%" : `${panelWidth}px` }}>
        {mode === "current" ? <div className="conversation-main"><SearchDiagnostics query="합성 진단 질문" diagnostics={{
          candidate_scope: "returned_hits", min_keyword_coverage: .5, min_semantic_score: .9,
          candidates: [], stages_ms: {}, agent_trace: trace,
        }} /></div> : <AgentTracePanel trace={mode === "empty" ? null : trace} view="history" />}
        <section aria-label="합성 처리 시간 비교">
          <h2>합성 처리 시간 비교</h2>
          <p>관측 시간만 비교합니다. 단계 합계를 전체 시간이나 진행률로 해석하지 않습니다.</p>
          <ExecutionStages stages={[
            { stage: "retrieval", state: "completed", duration_ms: 1000 },
            { stage: "generation", state: "completed", duration_ms: 9000 },
            { stage: "citation_validation", state: "completed", duration_ms: 0 },
            { stage: "persistence", state: "unrecorded", duration_ms: null },
          ]} />
        </section>
      </div>
    </main>
  </div>;
}

createRoot(document.getElementById("root")!).render(<Fixture />);
