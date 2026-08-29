import { apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";

export type ModelKind = components["schemas"]["ModelKind"];
export type ProfileKind = components["schemas"]["ProfileKind"];
export type EvaluationState = components["schemas"]["EvaluationState"];
export type JsonValue = components["schemas"]["JsonValue-Input"];
export type ModelDefinitionSummary = components["schemas"]["ModelResponse"];
export type ProfileBindingSummary = components["schemas"]["ProfileBindingCreate"];
export type ProfileSummary = components["schemas"]["ProfileResponse"];
type ModelCreate = components["schemas"]["ModelCreate"];
type ProfileYamlRequest = components["schemas"]["ProfileYamlRequest"];

export interface ModelLabData {
  models: ModelDefinitionSummary[];
  profiles: ProfileSummary[];
}

export async function loadModelLab(): Promise<ModelLabData> {
  const [models, ...profileGroups] = await Promise.all([
    apiRequest<ModelDefinitionSummary[]>("/api/v1/rag/models"),
    ...(["indexing", "retrieval", "generation"] as ProfileKind[]).map((kind) =>
      apiRequest<ProfileSummary[]>(`/api/v1/rag/profiles/${kind}`),
    ),
  ]);
  return { models, profiles: profileGroups.flat() };
}

export async function registerModelVersion(input: ModelCreate): Promise<ModelDefinitionSummary> {
  return apiRequest<ModelDefinitionSummary>("/api/v1/rag/models", {
    method: "POST",
    json: input,
  });
}

export async function registerYamlProfile(
  kind: ProfileKind,
  content: string,
): Promise<ProfileSummary> {
  const request: ProfileYamlRequest = { content };
  return apiRequest<ProfileSummary>(`/api/v1/rag/profiles/${kind}/yaml`, {
    method: "POST",
    json: request,
  });
}
