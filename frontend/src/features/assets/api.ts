import { apiRequest, decodeApiResponse } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type DocumentSummary = components["schemas"]["DocumentResponse"];
export type FolderSummary = components["schemas"]["FolderResponse"];
export type LibraryFolder = components["schemas"]["LibraryFolderResponse"];
export type LibraryPage = components["schemas"]["LibraryPageResponse"];
export type AssetVersion = components["schemas"]["AssetVersionResponse"];
export type AssetVersionPage = components["schemas"]["AssetVersionPageResponse"];
export type OriginalPreview = components["schemas"]["OriginalPreviewResponse"];
export type AssetMoveRequest = components["schemas"]["AssetMoveRequest"];
export type DocumentMoveResult = components["schemas"]["DocumentMoveResponse"];
export type FolderMoveResult = components["schemas"]["FolderMoveResponse"];

export function moveDocument(workspaceId: string, documentId: string, body: AssetMoveRequest, signal?: AbortSignal): Promise<DocumentMoveResult> {
  return apiRequest(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(documentId)}/move`, { method: "POST", json: { destination_folder_id: body.destination_folder_id, expected_revision: body.expected_revision }, signal });
}

export function moveFolder(workspaceId: string, folderId: string, body: AssetMoveRequest, signal?: AbortSignal): Promise<FolderMoveResult> {
  return apiRequest(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/folders/${encodeURIComponent(folderId)}/move`, { method: "POST", json: { destination_folder_id: body.destination_folder_id, expected_revision: body.expected_revision }, signal });
}

export type EvidenceApprovalStatus = "pending" | "approved" | "rejected";
export type EvidenceApprovalContextStatus = "unapproved" | "approved" | "revoked";
export type EvidenceApprovalProvider = "development_codex_exec";

export interface EvidenceApprovalContext {
  revision_id: string;
  provider: EvidenceApprovalProvider;
  approval_status: EvidenceApprovalContextStatus;
  approval_generation: number;
}

export interface EvidenceApprovalRequest {
  id: string;
  revision_id: string;
  provider: EvidenceApprovalProvider;
  status: EvidenceApprovalStatus;
  state_revision: number;
  created_at: string;
  resolved_at: string | null;
}

export interface EvidenceApprovalRequestList {
  items: EvidenceApprovalRequest[];
  next_cursor: string | null;
  context: EvidenceApprovalContext | null;
}

export interface EvidenceApprovalRequestCreate {
  request_id: string;
  revision_id: string;
  provider: EvidenceApprovalProvider;
  expected_approval_generation: number;
}

const evidenceHeaders = { "x-codex-request": "1" };
const evidenceProvider: EvidenceApprovalProvider = "development_codex_exec";

export function listEvidenceApprovalRequests(revisionId: string, signal?: AbortSignal): Promise<EvidenceApprovalRequestList> {
  const query = new URLSearchParams({
    revision_id: revisionId,
    provider: evidenceProvider,
  });
  return apiRequest<EvidenceApprovalRequestList>(`/api/v1/rag/evidence-approval-requests?${query.toString()}`, { signal });
}

export function requestEvidenceApproval(revisionId: string, body: EvidenceApprovalRequestCreate): Promise<EvidenceApprovalRequest> {
  return apiRequest<EvidenceApprovalRequest>("/api/v1/rag/evidence-approval-requests", {
    method: "POST",
    json: { ...body, revision_id: revisionId },
    headers: evidenceHeaders,
  });
}

export async function listDocuments(workspaceId: string): Promise<DocumentSummary[]> {
  return apiRequest<DocumentSummary[]>(`/api/v1/workspaces/${workspaceId}/documents`);
}

export async function uploadDocument(
  workspaceId: string,
  file: File,
  folderId: string | null = null,
): Promise<DocumentSummary> {
  const body = new FormData();
  body.append("file", file);
  if (folderId) body.append("folder_id", folderId);
  return apiRequest<DocumentSummary>(`/api/v1/workspaces/${workspaceId}/documents`, {
    method: "POST",
    body,
  });
}

export async function browseLibrary(workspaceId: string, options: {
  folderId?: string | null;
  folderCursor?: string | null;
  documentCursor?: string | null;
  signal?: AbortSignal;
} = {}): Promise<LibraryPage> {
  const query = new URLSearchParams();
  if (options.folderId) query.set("folder_id", options.folderId);
  if (options.folderCursor) query.set("folder_cursor", options.folderCursor);
  if (options.documentCursor) query.set("document_cursor", options.documentCursor);
  const suffix = query.size ? `?${query.toString()}` : "";
  return apiRequest<LibraryPage>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/library${suffix}`, { signal: options.signal });
}

export async function getLibraryDocument(workspaceId: string, documentId: string, signal?: AbortSignal): Promise<DocumentSummary> {
  return apiRequest<DocumentSummary>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/library/documents/${encodeURIComponent(documentId)}`, { signal });
}

export async function listLibraryDocumentVersions(workspaceId: string, documentId: string, cursor?: string | null, signal?: AbortSignal): Promise<AssetVersionPage> {
  const query = cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
  return apiRequest<AssetVersionPage>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/library/documents/${encodeURIComponent(documentId)}/versions${query}`, { signal });
}

export async function previewOriginal(documentId: string, versionId: string, signal?: AbortSignal): Promise<OriginalPreview> {
  return apiRequest<OriginalPreview>(`/api/v1/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/preview`, { signal });
}

export async function loadPdfPage(documentId: string, versionId: string, page: number, signal?: AbortSignal): Promise<Blob> {
  const response = await fetch(`/api/v1/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/pdf/pages/${page}`, { credentials: "include", signal });
  if (!response.ok) await decodeApiResponse<never>(response);
  return response.blob();
}

export function originalDownloadPath(documentId: string, versionId: string): string {
  return `/api/v1/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/content`;
}

export async function createFolder(workspaceId: string, name: string, parentId: string | null): Promise<FolderSummary> {
  return apiRequest<FolderSummary>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/folders`, { method: "POST", json: { name, parent_id: parentId } });
}

export async function uploadDocumentVersion(
  documentId: string,
  file: File,
): Promise<DocumentSummary> {
  const body = new FormData();
  body.append("file", file);
  return apiRequest<DocumentSummary>(`/api/v1/documents/${documentId}/versions`, {
    method: "POST",
    body,
  });
}
