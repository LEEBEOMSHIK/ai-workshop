import { apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";

export type DomainSearchRequest = components["schemas"]["DomainSearchRequest"];
export type DomainSearchResult = components["schemas"]["DomainSearchResponse"];
export type Evidence = components["schemas"]["EvidenceAnswerResponse"];
export type Folder = components["schemas"]["FolderResponse"];

export function searchDomain(
  slug: string,
  request: DomainSearchRequest,
  signal?: AbortSignal,
): Promise<DomainSearchResult> {
  return apiRequest<DomainSearchResult>(
    `/api/v1/rag/domains/${encodeURIComponent(slug)}/search`,
    { method: "POST", json: request, signal, ...(request.codex_input_approval ? { headers: { "x-codex-request": "1" } } : {}) },
  );
}

export function listConversationFolders(workspaceId: string, signal?: AbortSignal): Promise<Folder[]> {
  return apiRequest<Folder[]>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/folders`, { signal });
}
