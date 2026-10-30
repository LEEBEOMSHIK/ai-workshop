import type { DeploymentSummary, JsonValue } from "../models/api";
import type { SavedConfiguration, SavedConfigurationCreate } from "../configurations/api";

export function sameJson(left: unknown, right: unknown): boolean {
  function canonical(value: unknown): unknown {
    if (Array.isArray(value)) return value.map(canonical);
    if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).sort(([a],[b])=>a.localeCompare(b)).map(([key,item])=>[key,canonical(item)]));
    return value;
  }
  return JSON.stringify(canonical(left)) === JSON.stringify(canonical(right));
}

export function candidateRequest(base: SavedConfiguration, name: string, profileId: string,
  approval?: SavedConfigurationCreate["external_transfer_approval"]): SavedConfigurationCreate {
  const policy = base.answer_policy;
  return {
    name: name.trim(), document_processing_profile_id: base.document_processing_profile_id,
    indexing_profile_id: base.indexing_profile_id, retrieval_profile_id: base.retrieval_profile_id,
    generation_profile_id: profileId, workspace_ids: [...base.workspace_ids],
    answer_policy: { mode: "generative", min_semantic_score: policy.min_semantic_score,
      min_keyword_coverage: policy.min_keyword_coverage, require_complete_provenance: policy.require_complete_provenance,
      conflict_mode: policy.conflict_mode },
    ...(approval ? {external_transfer_approval: {...approval}} : {}),
  };
}

export function canApplyCandidate(config: SavedConfiguration): boolean {
  return config.answer_policy.mode === "generative" && config.evaluation_state === "passed"
    && config.search_ready && config.answer_ready && config.service_ready;
}

export function compatibleAnswerSettings(config: Record<string, JsonValue>,
  deployment: Pick<DeploymentSummary,"provider"|"location">): boolean {
  if (!["local_openai_compatible", "openai_responses", "anthropic_messages"].includes(deployment.provider)) return false;
  const generation = config.generation;
  const settings = typeof generation === "object" && generation !== null && !Array.isArray(generation) ? generation : {};
  const localOnly = ["rag-answer-v5", "rag-answer-v6"].includes(String(config.prompt_ref))
    || config.orchestration != null || settings.answer_reasoning_effort != null;
  if (localOnly && (deployment.provider !== "local_openai_compatible" || deployment.location !== "local")) return false;
  if (deployment.provider === "anthropic_messages") {
    const allowedConfig = ["prompt_ref", "context_prompt_ref", "citation_mode", "context_policy", "generation"];
    const allowedGeneration = ["timeout_seconds", "max_output_tokens", "temperature", "response_schema_version", "sampling_mode"];
    return deployment.location === "external" && config.prompt_ref === "rag-answer-v1"
      && config.context_prompt_ref === "rag-contextualize-v1" && config.citation_mode === "required"
      && Object.keys(config).length === allowedConfig.length && Object.keys(config).every(key => allowedConfig.includes(key))
      && Object.keys(settings).length === allowedGeneration.length && Object.keys(settings).every(key => allowedGeneration.includes(key))
      && settings.response_schema_version === 1 && settings.sampling_mode === "provider_default" && settings.temperature === 1;
  }
  if (settings.sampling_mode != null && settings.sampling_mode !== "explicit") return false;
  if (deployment.provider === "openai_responses" && settings.response_schema_version != null && settings.response_schema_version !== 1) return false;
  return true;
}

export function externalDisclosureVersion(provider: DeploymentSummary["provider"]):
  NonNullable<SavedConfigurationCreate["external_transfer_approval"]>["disclosure_version"] | undefined {
  if (provider === "anthropic_messages") return "anthropic-generation-v1";
  if (provider === "openai_responses") return "external-generation-v1";
  return undefined;
}
