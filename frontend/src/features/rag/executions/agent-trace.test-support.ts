import type { components } from "../../../shared/api/schema";

type AgentContent = components["schemas"]["AgentContent"];
type AgentSpan = components["schemas"]["AgentSpan"];
type AgentTrace = components["schemas"]["AgentTrace"];

export function syntheticContent(text: string): AgentContent {
  return { content_status: "complete", text, characters: text.length, sha256: "a".repeat(64) };
}

export function syntheticAgentTrace(retained = true): AgentTrace {
  const content = (text: string): AgentContent => retained
    ? syntheticContent(text)
    : { content_status: "not_retained", text: null, characters: text.length, sha256: "a".repeat(64) };
  const span = (value: Partial<AgentSpan> & Pick<AgentSpan, "id" | "parent_id" | "sequence" | "name" | "kind">): AgentSpan => ({
    state: "completed", started_at: "2026-10-23T01:30:00Z", ended_at: "2026-10-23T01:30:02Z",
    duration_ms: 2000, from_agent: null, to_agent: null, delegation_mode: null,
    model_name: null, input_kind: "sdk_input", instructions: content("합성 역할 지침"),
    input: content("합성 위임 작업"), output: content("합성 반환 결과"), input_tokens: null,
    output_tokens: null, error_code: null, evidence_refs: [], ...value,
  });
  return {
    schema_version: 1, runtime: "openai_agents", run_id: "synthetic-agent-run",
    content_retention: retained ? "retained" : "metadata_only",
    root_span_id: "manager", revision: 10, updated_at: "2026-10-23T01:30:05Z",
    observation_complete: true, truncated: false,
    spans: [
      span({ id: "manager", parent_id: null, sequence: 0, kind: "agent", name: "synthetic_manager" }),
      span({ id: "delegate", parent_id: "manager", sequence: 1, kind: "delegation", name: "synthetic_delegate",
        from_agent: "synthetic_manager", to_agent: "synthetic_writer", delegation_mode: "as_tool" }),
      span({ id: "writer", parent_id: "delegate", sequence: 2, kind: "agent", name: "synthetic_writer" }),
      span({ id: "tool", parent_id: "writer", sequence: 3, kind: "tool", name: "synthetic_evidence",
        input_kind: "tool_arguments", input: content('{"question":"합성 도구 질문"}'),
        output: content('{"evidence":"합성 도구 결과"}') }),
      span({ id: "model", parent_id: "writer", sequence: 4, kind: "model", name: "synthetic_generation",
        model_name: "synthetic-model", input_kind: "http_request", input_tokens: 0, output_tokens: 12,
        input: content('{"messages":[{"role":"user","content":"합성 실제 요청 <script>unsafe()</script>"}]}') }),
    ],
  };
}

export function syntheticDeepAgentTrace(): AgentTrace {
  const trace = syntheticAgentTrace(false);
  return { ...trace, run_id: "synthetic-deep-run", root_span_id: "nested-1",
    spans: Array.from({ length: 64 }, (_, index) => ({ ...trace.spans[0],
      id: `nested-${index + 1}`, parent_id: index ? `nested-${index}` : null,
      name: `synthetic_nested_${index + 1}`, sequence: index,
    })),
  };
}

// Same parent structure as the SDK's manager/model/delegation/specialist/model flow.
// All identifiers, bodies, models and timings remain synthetic.
export function syntheticSteppedAgentTrace(retained = true): AgentTrace {
  const trace = syntheticAgentTrace(retained);
  const [manager, delegate, writer, , model] = trace.spans;
  return { ...trace, run_id: "synthetic-stepped-run", spans: [
    manager,
    { ...model, id: "manager-model", parent_id: manager.id, sequence: 1,
      name: "synthetic_coordination", model_name: "synthetic-manager-model" },
    { ...delegate, sequence: 2 },
    { ...writer, sequence: 3 },
    model,
  ] };
}

export function syntheticBranchAgentTrace(): AgentTrace {
  const trace = syntheticAgentTrace(false);
  const [manager, delegate, writer, tool, model] = trace.spans;
  const secondDelegation: AgentSpan = { ...delegate, id: "review-delegate", parent_id: manager.id,
    sequence: 5, name: "synthetic_review_delegate", to_agent: "synthetic_reviewer", delegation_mode: "handoff" };
  const reviewer: AgentSpan = { ...writer, id: "reviewer", parent_id: secondDelegation.id,
    sequence: 6, name: "synthetic_reviewer" };
  const reviewModel: AgentSpan = { ...model, id: "review-model", parent_id: reviewer.id,
    sequence: 7, name: "synthetic_review_model", model_name: "synthetic-review-model" };
  const managerModel: AgentSpan = { ...model, id: "manager-model", parent_id: manager.id,
    sequence: 8, name: "synthetic_manager_model", model_name: "synthetic-manager-model" };
  return { ...trace, run_id: "synthetic-branch-run",
    spans: [reviewModel, model, reviewer, managerModel, manager, tool, secondDelegation, writer, delegate],
  };
}
