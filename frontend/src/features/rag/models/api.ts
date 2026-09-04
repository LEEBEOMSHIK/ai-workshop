import { ApiError, apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";

export type ModelKind = components["schemas"]["ModelKind"];
export type ProfileKind = components["schemas"]["ProfileKind"];
export type EvaluationState = components["schemas"]["EvaluationState"];
export type JsonValue = components["schemas"]["JsonValue-Input"];
export type ModelDefinitionSummary = components["schemas"]["ModelResponse"];
export type ProfileBindingSummary = components["schemas"]["ProfileBindingCreate"];
export type ProfileSummary = components["schemas"]["ProfileResponse"];
export type DeploymentSummary = components["schemas"]["DeploymentAdminResponse"];
export type DeploymentHealth = components["schemas"]["DeploymentHealthResponse"];
export type InstallationDataPolicy = components["schemas"]["InstallationDataPolicyResponse"];
export type InstallationDataPolicyCreate = components["schemas"]["InstallationDataPolicyCreate"];
export type WorkspaceDataPolicy = components["schemas"]["WorkspaceDataPolicyResponse"];
export type WorkspaceDataPolicyCreate = components["schemas"]["WorkspaceDataPolicyCreate"];
export type WorkspaceSummary = components["schemas"]["WorkspaceResponse"];
type ModelCreate = components["schemas"]["ModelCreate"];
type ProfileYamlRequest = components["schemas"]["ProfileYamlRequest"];

export interface ModelLabData {
  models: ModelDefinitionSummary[];
  profiles: ProfileSummary[];
}

export interface ModelAdministrationData {
  deployments: DeploymentSummary[];
  installationPolicy: InstallationDataPolicy;
  workspaces: WorkspaceSummary[];
  workspacePolicies: Record<string, WorkspaceDataPolicy | null>;
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

export async function loadDeployments(): Promise<DeploymentSummary[]> {
  return apiRequest<DeploymentSummary[]>("/api/v1/admin/rag/deployments");
}

export async function checkDeploymentHealth(versionId: string): Promise<DeploymentHealth> {
  return apiRequest<DeploymentHealth>(
    `/api/v1/admin/rag/deployment-versions/${encodeURIComponent(versionId)}/health-check`,
    { method: "POST" },
  );
}

export async function loadInstallationPolicy(): Promise<InstallationDataPolicy> {
  return apiRequest<InstallationDataPolicy>(
    "/api/v1/admin/rag/data-policies/installation",
  );
}

export async function loadWorkspacePolicy(workspaceId: string): Promise<WorkspaceDataPolicy> {
  return apiRequest<WorkspaceDataPolicy>(
    `/api/v1/admin/rag/data-policies/workspaces/${encodeURIComponent(workspaceId)}`,
  );
}

export async function loadModelAdministration(): Promise<ModelAdministrationData> {
  const [deployments, installationPolicy, workspaces] = await Promise.all([
    loadDeployments(),
    loadInstallationPolicy(),
    apiRequest<WorkspaceSummary[]>("/api/v1/workspaces"),
  ]);
  const policyEntries = await Promise.all(workspaces.map(async (workspace) => {
    try {
      return [workspace.id, await loadWorkspacePolicy(workspace.id)] as const;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) {
        return [workspace.id, null] as const;
      }
      throw error;
    }
  }));
  return {
    deployments,
    installationPolicy,
    workspaces,
    workspacePolicies: Object.fromEntries(policyEntries),
  };
}

export function createInstallationPolicy(
  request: InstallationDataPolicyCreate,
): Promise<InstallationDataPolicy> {
  return apiRequest<InstallationDataPolicy>(
    "/api/v1/admin/rag/data-policies/installation/versions",
    { method: "POST", json: request },
  );
}

export function createWorkspacePolicy(
  workspaceId: string,
  request: WorkspaceDataPolicyCreate,
): Promise<WorkspaceDataPolicy> {
  return apiRequest<WorkspaceDataPolicy>(
    `/api/v1/admin/rag/data-policies/workspaces/${encodeURIComponent(workspaceId)}/versions`,
    { method: "POST", json: request },
  );
}

export async function registerModelVersion(input: ModelCreate): Promise<ModelDefinitionSummary> {
  return apiRequest<ModelDefinitionSummary>("/api/v1/admin/rag/models", {
    method: "POST",
    json: input,
  });
}

export async function registerYamlProfile(
  kind: ProfileKind,
  content: string,
): Promise<ProfileSummary> {
  const request: ProfileYamlRequest = { content };
  return apiRequest<ProfileSummary>(`/api/v1/admin/rag/profiles/${kind}/yaml`, {
    method: "POST",
    json: request,
  });
}
