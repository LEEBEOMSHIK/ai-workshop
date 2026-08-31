import { ApiError, apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";

export type EvidenceAnswerData = components["schemas"]["EvidenceAnswerResponse"];
export type FolderOption = components["schemas"]["FolderResponse"];
export type HighlightSpan = components["schemas"]["HighlightSpanResponse"];
export type NormalizedTextData = components["schemas"]["NormalizedTextResponse"];
export type RelatedSourceData = components["schemas"]["RelatedSourceResponse"];
export type SavedConfiguration = components["schemas"]["SavedRagConfigurationResponse"];
export type SearchRequest = components["schemas"]["SearchRequest"];
export type SearchResult = components["schemas"]["SearchResponse"];
export type WorkspaceOption = components["schemas"]["WorkspaceResponse"];

export interface SearchOptions {
  configurations: SavedConfiguration[];
  workspaces: WorkspaceOption[];
}

export interface SearchSubmissionContext {
  readonly query: string;
  readonly configuration: {
    readonly id: string;
    readonly versionId: string;
    readonly version: number;
    readonly name: string;
    readonly experimental: boolean;
  };
  readonly workspaces: ReadonlyArray<{
    readonly id: string;
    readonly name: string;
    readonly kind: WorkspaceOption["kind"];
  }>;
  readonly folders: ReadonlyArray<{
    readonly id: string;
    readonly name: string;
    readonly workspaceId: string;
  }>;
  readonly experimentalConsent: boolean;
}

export async function loadSearchOptions(): Promise<SearchOptions> {
  const [workspaces, configurations] = await Promise.all([
    apiRequest<WorkspaceOption[]>("/api/v1/workspaces"),
    apiRequest<SavedConfiguration[]>("/api/v1/rag/configurations"),
  ]);
  return { configurations, workspaces };
}

export function searchEvidence(request: SearchRequest, signal?: AbortSignal): Promise<SearchResult> {
  return apiRequest<SearchResult>("/api/v1/rag/search", {
    method: "POST",
    json: request,
    signal,
  });
}

export function listSearchFolders(workspaceId: string): Promise<FolderOption[]> {
  return apiRequest<FolderOption[]>(`/api/v1/workspaces/${workspaceId}/folders`);
}

export function loadNormalizedText(
  assetVersionId: string,
  projectionId: string,
): Promise<NormalizedTextData> {
  const query = new URLSearchParams({ projection_id: projectionId });
  return apiRequest<NormalizedTextData>(
    `/api/v1/rag/sources/${assetVersionId}/normalized-text?${query}`,
  );
}

export async function loadPdfPage(
  assetVersionId: string,
  projectionId: string,
  page: number,
): Promise<Blob> {
  const query = new URLSearchParams({ projection_id: projectionId });
  const response = await fetch(
    `/api/v1/rag/sources/${assetVersionId}/pdf/pages/${page}?${query}`,
    { credentials: "include" },
  );
  if (!response.ok) {
    throw new ApiError("원문 페이지를 불러오지 못했습니다.", response.status, "source_failed");
  }
  return response.blob();
}
