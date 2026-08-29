import { apiRequest } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type DocumentSummary = components["schemas"]["DocumentResponse"];

export async function listDocuments(workspaceId: string): Promise<DocumentSummary[]> {
  return apiRequest<DocumentSummary[]>(`/api/v1/workspaces/${workspaceId}/documents`);
}

export async function uploadDocument(
  workspaceId: string,
  file: File,
): Promise<DocumentSummary> {
  const body = new FormData();
  body.append("file", file);
  return apiRequest<DocumentSummary>(`/api/v1/workspaces/${workspaceId}/documents`, {
    method: "POST",
    body,
  });
}
