import { DocumentPage } from "../../../../../../features/assets/DocumentPage";
import type { DocumentSummary, LibraryPage } from "../../../../../../features/assets/api";
import type { WorkspaceSummary } from "../../../../../../features/workspaces/api";
import { ApiError } from "../../../../../../shared/api/client";
import { serverApiRequest } from "../../../../../../shared/api/server-client";
import {
  incomingCookieHeader,
  requireWorkspaceUser,
} from "../../../../../../shared/auth/server-session";
import { workspaceDocumentPath } from "../../../../../../shared/routing/routes";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../../../../shared/ui/ServerRouteFailure";

interface DocumentsRouteProps {
  params: Promise<{ workspaceId: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function DocumentsRoute({ params, searchParams }: DocumentsRouteProps) {
  const { workspaceId } = await params;
  const query = await searchParams;
  const folderId = one(query.folder);
  const documentId = one(query.document);
  const versionId = one(query.version);
  const result = await captureServerRoute(async () => {
    await requireWorkspaceUser(workspaceDocumentPath(workspaceId));
    const cookie = await incomingCookieHeader();
    if (versionId && !documentId) throw new ApiError("Not found", 404, "library_document_not_found");
    const [workspaces, exactDocument] = await Promise.all([
      serverApiRequest<WorkspaceSummary[]>("/api/v1/workspaces", {}, cookie),
      documentId ? serverApiRequest<DocumentSummary>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/library/documents/${encodeURIComponent(documentId)}`, {}, cookie) : Promise.resolve(null),
    ]);
    if (exactDocument && folderId && exactDocument.folder_id !== folderId) {
      throw new ApiError("Not found", 404, "library_document_not_found");
    }
    const selectedFolderId = exactDocument?.folder_id ?? folderId;
    const selectedPath = `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/library${selectedFolderId ? `?folder_id=${encodeURIComponent(selectedFolderId)}` : ""}`;
    const initialLibrary = await serverApiRequest<LibraryPage>(selectedPath, {}, cookie);
    const initialRoot = selectedFolderId
      ? await serverApiRequest<LibraryPage>(`/api/v1/workspaces/${encodeURIComponent(workspaceId)}/library`, {}, cookie)
      : initialLibrary;
    return { workspaces, exactDocument, initialLibrary, initialRoot };
  });
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  return <DocumentPage workspaceId={workspaceId} initialLibrary={result.value.initialLibrary} initialRoot={result.value.initialRoot} initialWorkspaces={result.value.workspaces} initialDocument={result.value.exactDocument} initialVersionId={versionId} />;
}

function one(value: string | string[] | undefined): string | null {
  return typeof value === "string" && value ? value : null;
}
