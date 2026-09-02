import { apiRequest } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type WorkspaceKind = components["schemas"]["WorkspaceKind"];
export type WorkspaceSummary = components["schemas"]["WorkspaceResponse"];

export async function listWorkspaces(): Promise<WorkspaceSummary[]> {
  return apiRequest<WorkspaceSummary[]>("/api/v1/workspaces");
}
