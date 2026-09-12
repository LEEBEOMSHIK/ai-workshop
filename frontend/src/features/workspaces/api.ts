import { apiRequest } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type WorkspaceKind = components["schemas"]["WorkspaceKind"];
export type WorkspaceSummary = components["schemas"]["WorkspaceResponse"];
export type WorkspaceCreate = components["schemas"]["WorkspaceCreate"];

export async function createWorkspace(request: WorkspaceCreate): Promise<WorkspaceSummary> {
  return apiRequest<WorkspaceSummary>("/api/v1/workspaces", { method: "POST", json: request });
}

export async function listWorkspaces(): Promise<WorkspaceSummary[]> {
  return apiRequest<WorkspaceSummary[]>("/api/v1/workspaces");
}
