import { describe, expect, it } from "vitest";
import type { SavedConfiguration } from "../configurations/api";
import { candidateRequest, canApplyCandidate, compatibleAnswerSettings, externalDisclosureVersion } from "./candidate";

export const baseConfiguration = {
  id: "config", version_id: "version", name: "기존 구성", version: 7,
  document_processing_profile_id: "parser", indexing_profile_id: "index", retrieval_profile_id: "search",
  generation_profile_id: "generation", workspace_ids: ["space-b", "space-a"],
  answer_policy: { id: "policy", version: 3, mode: "generative", min_semantic_score: .81,
    min_keyword_coverage: .67, require_complete_provenance: true, conflict_mode: "separate_sources" },
  evaluation_state: "passed", service_ready: true, search_ready: true, answer_ready: true,
  is_system: false, is_default: false, experimental: false, owner_id: "owner",
  search_reasons: [], answer_reasons: [], generation_execution_preview: null,
} satisfies SavedConfiguration;

describe("guided RAG candidate", () => {
  it("requires Claude's explicit compatible profile and a separate recipient confirmation", () => {
    const claude = {provider:"anthropic_messages",location:"external"} as const;
    const config = {prompt_ref:"rag-answer-v1",context_prompt_ref:"rag-contextualize-v1",citation_mode:"required",
      context_policy:{max_history_turns:6,max_history_tokens:1024},
      generation:{response_schema_version:1,sampling_mode:"provider_default",temperature:1,max_output_tokens:1024,timeout_seconds:120}};
    expect(compatibleAnswerSettings(config,claude)).toBe(true);
    expect(compatibleAnswerSettings({...config,generation:{...config.generation,sampling_mode:"explicit"}},claude)).toBe(false);
    expect(compatibleAnswerSettings({...config,generation:{...config.generation,temperature:0}},claude)).toBe(false);
    expect(compatibleAnswerSettings({...config,orchestration:{engine:"openai_agents"}},claude)).toBe(false);
    expect(compatibleAnswerSettings({...config,context_evidence:{max_groups:1}},claude)).toBe(false);
    expect(compatibleAnswerSettings(config,{provider:"openai_responses",location:"external"})).toBe(false);
    expect(externalDisclosureVersion(claude.provider)).toBe("anthropic-generation-v1");
    expect(externalDisclosureVersion("openai_responses")).toBe("external-generation-v1");
    expect(externalDisclosureVersion("local_openai_compatible")).toBeUndefined();
  });
  it("copies exact search, source scope and thresholds without mutating baseline", () => {
    const snapshot = structuredClone(baseConfiguration);
    const request = candidateRequest(baseConfiguration, "새 후보", "new-generation");
    expect(request).toEqual({name:"새 후보", document_processing_profile_id:"parser", indexing_profile_id:"index",
      retrieval_profile_id:"search", generation_profile_id:"new-generation", workspace_ids:["space-b","space-a"],
      answer_policy:{mode:"generative", min_semantic_score:.81,min_keyword_coverage:.67,
        require_complete_provenance:true,conflict_mode:"separate_sources"}});
    request.workspace_ids.push("new-space");
    expect(baseConfiguration).toEqual(snapshot);
  });
  it("only attaches a supplied fresh external confirmation", () => {
    const request = candidateRequest(baseConfiguration,"후보","profile",{confirmed:true,disclosure_version:"external-generation-v1"});
    expect(request.external_transfer_approval).toEqual({confirmed:true,disclosure_version:"external-generation-v1"});
    expect(candidateRequest(baseConfiguration,"후보","profile").external_transfer_approval).toBeUndefined();
  });
  it.each(["draft", "pending", "failed"] as const)("blocks %s even when healthy", state => {
    expect(canApplyCandidate({...baseConfiguration,evaluation_state:state})).toBe(false);
  });
  it("requires a generative, fully ready accepted configuration", () => {
    expect(canApplyCandidate(baseConfiguration)).toBe(true);
    expect(canApplyCandidate({...baseConfiguration,service_ready:false})).toBe(false);
    expect(canApplyCandidate({...baseConfiguration,answer_ready:false})).toBe(false);
    expect(canApplyCandidate({...baseConfiguration,answer_policy:{...baseConfiguration.answer_policy,mode:"extractive"}})).toBe(false);
  });
  it("does not silently strip local-only settings when switching to OpenAI", () => {
    const config = {prompt_ref:"rag-answer-v6",generation:{answer_reasoning_effort:"none"},orchestration:{engine:"openai_agents"}};
    const original = structuredClone(config);
    expect(compatibleAnswerSettings(config,{provider:"openai_responses",location:"external"})).toBe(false);
    expect(config).toEqual(original);
    expect(compatibleAnswerSettings(config,{provider:"local_openai_compatible",location:"local"})).toBe(true);
    expect(compatibleAnswerSettings({prompt_ref:"rag-answer-v3"},{provider:"openai_responses",location:"external"})).toBe(true);
  });
});
