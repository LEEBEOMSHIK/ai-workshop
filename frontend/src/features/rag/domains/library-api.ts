import { apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";
import type { DocumentSummary, LibraryPage } from "../../assets/api";

export type DomainLibraryContext = components["schemas"]["DomainLibraryResponse"];

export function getDomainLibraryContext(slug: string, signal?: AbortSignal): Promise<DomainLibraryContext> {
  return apiRequest<DomainLibraryContext>(`/api/v1/rag/domains/${encodeURIComponent(slug)}/library`, { signal });
}

export function browseDomainLibrary(slug: string, workspaceId: string, options: {
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
  return apiRequest<LibraryPage>(`/api/v1/rag/domains/${encodeURIComponent(slug)}/library/workspaces/${encodeURIComponent(workspaceId)}${suffix}`, { signal: options.signal });
}

export function getDomainLibraryDocument(slug: string, workspaceId: string, documentId: string, signal?: AbortSignal): Promise<DocumentSummary> {
  return apiRequest<DocumentSummary>(`/api/v1/rag/domains/${encodeURIComponent(slug)}/library/workspaces/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(documentId)}`, { signal });
}
