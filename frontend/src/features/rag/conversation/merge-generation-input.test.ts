import type { ConversationDetail } from "./sessions-api";
import { mergeGenerationInput } from "./merge-generation-input";

function detail(captured = false): ConversationDetail {
  return { id: "session", revision: 2, title: "Synthetic question", title_origin: "auto", legacy_state: "active",
    created_at: "2026-10-16", updated_at: "2026-10-16", turns: [{
      id: "turn", request_id: "request", sequence: 1, segment: 1, status: "completed",
      query: "Synthetic question", redacted: false, execution_terminated: true, error_code: null,
      created_at: "2026-10-16", updated_at: "2026-10-16",
      request_scope: { connection_version_id: "connection", workspace_ids: ["workspace"], folder_ids: [], document_ids: null },
      response: { status: "insufficient_evidence", answer: null, conflict_state: "none", conflicts: [], warnings: [],
        related_sources: [], experimental: false, resolved_query: "Synthetic question", selected_scope: null,
        configuration_version: { configuration_id: "config", version_id: "version", version: 1 },
        domain_context: { domain_id: "domain", connection_version_id: "connection", workspace_ids: ["workspace"], folder_ids: [] },
        generation: { status: "insufficient_evidence", text: null, citations: [], reason_codes: [], turn_id: "turn", validation_token: null, execution: null },
        diagnostics: { candidate_scope: "returned_hits", candidates: [], stages_ms: {}, min_keyword_coverage: 0.5, min_semantic_score: 0.9,
          generation_input: captured ? { status: "response_received", provider: "local_openai_compatible", dialect: "chat_completions",
            model: "Synthetic model", model_version: 1, prompt_ref: "rag-answer-v3", profile_version: 1, request_json: null,
            content_status: "omitted_size_limit", body_characters: 300000, body_bytes: 300000, capture_limit_characters: 100000,
            sha256: "a".repeat(64), max_output_tokens: 128, evidence_budget: null, provider_truncation: "unknown" } : null },
      },
    }] };
}

it("only adds input capture to an otherwise identical recovered completed turn", () => {
  const current = detail(); const posted = detail(true);
  const result = mergeGenerationInput(current, posted, "request");
  expect(result).not.toBe(current);
  expect(result?.turns[0].response?.diagnostics?.generation_input).toBe(posted.turns[0].response?.diagnostics?.generation_input);
  expect(current.turns[0].response?.diagnostics?.generation_input).toBeNull();
  expect({ ...result, turns: current.turns }).toEqual(current);
  expect({ ...result!.turns[0], response: current.turns[0].response }).toEqual(current.turns[0]);
  expect(mergeGenerationInput(result, posted, "request")).toBe(result);
});

it("matches JSON values independent of object key insertion order", () => {
  const posted = detail(true);
  const response = posted.turns[0].response!;
  posted.turns[0].response = Object.fromEntries(Object.entries(response).reverse()) as typeof response;
  expect(mergeGenerationInput(detail(), posted, "request")?.turns[0].response?.diagnostics?.generation_input).toBeTruthy();
});

it("allows transient POST observation completion but retains the stored GET value", () => {
  const current = detail(); const posted = detail(true);
  current.turns[0].observation_complete = null;
  posted.turns[0].observation_complete = true;
  const merged = mergeGenerationInput(current, posted, "request");
  expect(merged?.turns[0].response?.diagnostics?.generation_input).toBeTruthy();
  expect(merged?.turns[0].observation_complete).toBeNull();
});

it.each(["current", "posted"] as const)("refuses unsafe %s state", (side) => {
  const changes: Array<(value: ConversationDetail) => void> = [
    value => { value.id = "other"; }, value => { value.revision = 3; },
    value => { value.turns[0].id = "other"; }, value => { value.turns[0].request_id = "other"; },
    value => { value.turns[0].status = "failed"; }, value => { value.turns[0].status = "cancelled"; },
    value => { value.turns[0].status = "running"; }, value => { value.turns[0].redacted = true; },
    value => { value.turns[0].request_scope = null; }, value => { value.turns[0].execution_terminated = false; },
    value => { value.turns[0].query = "changed"; }, value => { value.turns[0].response = null; },
    value => { value.turns[0].response!.resolved_query = "changed"; },
    value => { value.turns[0].request_scope!.workspace_ids = ["other"]; },
    value => { value.turns[0].response!.diagnostics!.candidates = []; value.turns[0].response!.diagnostics!.warning = "different"; },
  ];
  for (const change of changes) {
    const current = detail(); const posted = detail(true);
    change(side === "current" ? current : posted);
    expect(mergeGenerationInput(current, posted, "request")).toBe(current);
  }
});

it("does not replace an existing capture or create missing response diagnostics", () => {
  const current = detail(true); const posted = detail(true);
  expect(mergeGenerationInput(current, posted, "request")).toBe(current);
  expect(mergeGenerationInput(null, posted, "request")).toBeNull();
  expect(mergeGenerationInput(current, posted, "other")).toBe(current);
  const missing = detail(); missing.turns[0].response!.diagnostics = null;
  expect(mergeGenerationInput(missing, posted, "request")).toBe(missing);
  expect(mergeGenerationInput(detail(), detail(), "request")?.turns[0].response?.diagnostics?.generation_input).toBeNull();
});
