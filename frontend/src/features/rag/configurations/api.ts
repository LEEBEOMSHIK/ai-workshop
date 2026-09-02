import { apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";
import { loadModelLab } from "../models/api";

export type EvaluationCandidate = components["schemas"]["EvaluationCandidateResponse"];
export type EvaluationMetrics = components["schemas"]["EvaluationMetricsResponse"];
export type EvaluationRun = components["schemas"]["EvaluationRunResponse"];
export type EvaluationRunCreate = components["schemas"]["EvaluationRunCreate"];
export type ModelDefinition = components["schemas"]["ModelResponse"];
export type Profile = components["schemas"]["ProfileResponse"];
export type SavedConfiguration = components["schemas"]["SavedRagConfigurationResponse"];
export type SavedConfigurationCreate = components["schemas"]["SavedRagConfigurationCreate"];
export type Workspace = components["schemas"]["WorkspaceResponse"];

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
