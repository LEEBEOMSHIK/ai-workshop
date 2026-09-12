import { apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";
import { loadModelLab } from "../models/api";

export type EvaluationCandidate = components["schemas"]["EvaluationCandidateResponse"];
export type EvaluationMetrics = components["schemas"]["EvaluationMetricsResponse"];
export type EvaluationRun = components["schemas"]["EvaluationRunResponse"];
export type EvaluationRunCreate = components["schemas"]["EvaluationRunCreate"];
export type DeploymentOption = components["schemas"]["DeploymentOptionResponse"];
export type ModelDefinition = components["schemas"]["ModelResponse"];
export type Profile = components["schemas"]["ProfileResponse"];
export type SavedConfiguration = components["schemas"]["SavedRagConfigurationResponse"];
export type SavedConfigurationCreate = components["schemas"]["SavedRagConfigurationCreate"];
export type Workspace = components["schemas"]["WorkspaceResponse"];
export type AuthoringDocumentsRequest = components["schemas"]["AuthoringDocumentsRequest"];
export type AuthoringDocumentsResponse = components["schemas"]["AuthoringDocumentsResponse"];
export type AuthoringScope = components["schemas"]["AuthoringScope"];
export type AuthoringPreview = components["schemas"]["AuthoringPreview"];
export type AuthoringEvidence = components["schemas"]["AuthoringEvidence"];
export type AuthoringCase = components["schemas"]["AuthoringCase"];
export type AuthoringRunRequest = components["schemas"]["AuthoringRunRequest"];
export type EvaluationPolicyCreate = components["schemas"]["EvaluationPolicyCreate"];
export type EvaluationPolicy = components["schemas"]["EvaluationPolicyResponse"];
export type EvaluationAcceptance = components["schemas"]["EvaluationAcceptanceResponse"];

export function listEvaluationDocuments(request: AuthoringDocumentsRequest, signal?: AbortSignal): Promise<AuthoringDocumentsResponse> {
  return apiRequest("/api/v1/rag/evaluation-authoring/documents", { method: "POST", json: request, signal });
}
export function previewEvaluationSources(request: AuthoringScope, signal?: AbortSignal): Promise<AuthoringPreview> {
  return apiRequest("/api/v1/rag/evaluation-authoring/preview", { method: "POST", json: request, signal });
}
export function startAuthoredEvaluation(request: AuthoringRunRequest, signal?: AbortSignal): Promise<EvaluationRun> {
  return apiRequest("/api/v1/rag/evaluation-authoring/runs", { method: "POST", json: request, signal });
}
export function createEvaluationPolicy(request: EvaluationPolicyCreate, signal?: AbortSignal): Promise<EvaluationPolicy> {
  return apiRequest("/api/v1/rag/evaluation-policies", { method: "POST", json: request, signal });
}
export function acceptConfigurationEvaluation(configurationId: string, versionId: string, runId: string, signal?: AbortSignal): Promise<EvaluationAcceptance> {
  return apiRequest(`/api/v1/rag/configurations/${encodeURIComponent(configurationId)}/versions/${encodeURIComponent(versionId)}/evaluation-acceptance`, { method: "POST", json: { evaluation_run_id: runId }, signal });
}

export interface ConfigurationStudioData {
  configurations: SavedConfiguration[];
  models: ModelDefinition[];
  profiles: Profile[];
  workspaces: Workspace[];
  runs: EvaluationRun[];
}

export async function loadConfigurationStudio(): Promise<ConfigurationStudioData> {
  const [configurations, modelLab, workspaces, runs] = await Promise.all([
    loadConfigurations(),
    loadModelLab(),
    apiRequest<Workspace[]>("/api/v1/workspaces"),
    apiRequest<EvaluationRun[]>("/api/v1/rag/evaluation-runs?limit=20"),
  ]);
  return {
    configurations,
    models: modelLab.models,
    profiles: modelLab.profiles,
    workspaces,
    runs,
  };
}

export function loadConfigurations(signal?: AbortSignal): Promise<SavedConfiguration[]> {
  return apiRequest<SavedConfiguration[]>("/api/v1/rag/configurations", { signal });
}

export function loadDeploymentOptions(signal?: AbortSignal): Promise<DeploymentOption[]> {
  return apiRequest<DeploymentOption[]>("/api/v1/rag/deployments/options", { signal });
}

export function saveConfiguration(
  request: SavedConfigurationCreate,
  signal?: AbortSignal,
): Promise<SavedConfiguration> {
  return apiRequest<SavedConfiguration>("/api/v1/rag/configurations", {
    method: "POST",
    json: request,
    signal,
  });
}

export function startEvaluationRun(
  request: EvaluationRunCreate,
  signal?: AbortSignal,
): Promise<EvaluationRun> {
  return apiRequest<EvaluationRun>("/api/v1/rag/evaluation-runs", {
    method: "POST",
    json: request,
    signal,
  });
}

export function loadEvaluationRun(runId: string, signal?: AbortSignal): Promise<EvaluationRun> {
  return apiRequest<EvaluationRun>(
    `/api/v1/rag/evaluation-runs/${encodeURIComponent(runId)}`,
    { signal },
  );
}

export function promoteConfiguration(
  configurationId: string,
  signal?: AbortSignal,
): Promise<SavedConfiguration> {
  return apiRequest<SavedConfiguration>(
    `/api/v1/rag/configurations/${encodeURIComponent(configurationId)}/default`,
    { method: "POST", signal },
  );
}
