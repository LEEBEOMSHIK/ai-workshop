import { apiRequest } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type WorkspaceKind = components["schemas"]["WorkspaceKind"];
export type WorkspaceSummary = components["schemas"]["WorkspaceResponse"];
export type WorkspaceCreate = components["schemas"]["WorkspaceCreate"];
export type WorkspaceCapabilities = components["schemas"]["WorkspaceCapabilitiesResponse"];
export type WorkspaceMember = components["schemas"]["WorkspaceMemberResponse"];
export type WorkspaceMemberPage = components["schemas"]["WorkspaceMemberPage"];
export type WorkspaceMemberPut = components["schemas"]["WorkspaceMemberPut"];

export async function createWorkspace(request: WorkspaceCreate): Promise<WorkspaceSummary> {
  return apiRequest<WorkspaceSummary>("/api/v1/workspaces", { method: "POST", json: request });
}

export async function listWorkspaces(): Promise<WorkspaceSummary[]> {
  return apiRequest<WorkspaceSummary[]>("/api/v1/workspaces");
}

export async function getWorkspaceCapabilities(workspaceId: string, signal?: AbortSignal): Promise<WorkspaceCapabilities> {
  return apiRequest<WorkspaceCapabilities>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/capabilities`, { signal });
}

export async function listWorkspaceMembers(workspaceId: string, after?: string | null, signal?: AbortSignal): Promise<WorkspaceMemberPage> {
  const query = after ? `?${new URLSearchParams({ after }).toString()}` : "";
  return apiRequest<WorkspaceMemberPage>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/members${query}`, { signal });
}

export async function putWorkspaceMember(
  workspaceId: string,
  userId: string,
  request: WorkspaceMemberPut,
  signal?: AbortSignal,
): Promise<WorkspaceMember> {
  return apiRequest<WorkspaceMember>(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/members/${encodeURIComponent(userId)}`,
    { method: "PUT", json: request, signal },
  );
}
