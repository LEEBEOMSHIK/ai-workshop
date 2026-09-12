import { ApiError } from "../../../../../../../shared/api/client";
import { serverApiRequest } from "../../../../../../../shared/api/server-client";
import { incomingCookieHeader, requireWorkspaceUser } from "../../../../../../../shared/auth/server-session";
import { ragDomainFilesPath } from "../../../../../../../shared/routing/routes";
import { captureServerRoute, ServerRouteFailure } from "../../../../../../../shared/ui/ServerRouteFailure";
import type { DocumentSummary, LibraryPage } from "../../../../../../../features/assets/api";
import { DomainFileCabinet } from "../../../../../../../features/rag/domains/DomainFileCabinet";
import type { DomainLibraryContext } from "../../../../../../../features/rag/domains/library-api";

interface DomainFilesRouteProps {
  params: Promise<{ slug: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}

export default async function RagDomainFilesRoute({ params, searchParams }: DomainFilesRouteProps) {
  const [{ slug }, query] = await Promise.all([params, searchParams]);
  const requestedWorkspaceId = one(query.workspace);
  const folderId = one(query.folder);
  const documentId = one(query.document);
  const versionId = one(query.version);
  const result = await captureServerRoute(async () => {
    await requireWorkspaceUser(ragDomainFilesPath(slug));
    const cookie = await incomingCookieHeader();
    const base = `/api/v1/rag/domains/${encodeURIComponent(slug)}/library`;
    const context = await serverApiRequest<DomainLibraryContext>(base, {}, cookie);
    const workspaceId = requestedWorkspaceId ?? context.workspace_options[0]?.id;
    if (!workspaceId || !context.workspace_options.some((workspace) => workspace.id === workspaceId)) throw notFound();
    if (versionId && !documentId) throw notFound();
    const exactDocument = documentId
      ? await serverApiRequest<DocumentSummary>(`${base}/workspaces/${encodeURIComponent(workspaceId)}/documents/${encodeURIComponent(documentId)}`, {}, cookie)
      : null;
    if (exactDocument && (exactDocument.workspace_id !== workspaceId || (folderId && exactDocument.folder_id !== folderId))) throw notFound();
    const selectedFolderId = exactDocument?.folder_id ?? folderId;
    const library = await serverApiRequest<LibraryPage>(`${base}/workspaces/${encodeURIComponent(workspaceId)}${selectedFolderId ? `?folder_id=${encodeURIComponent(selectedFolderId)}` : ""}`, {}, cookie);
    const root = selectedFolderId ? await serverApiRequest<LibraryPage>(`${base}/workspaces/${encodeURIComponent(workspaceId)}`, {}, cookie) : library;
    return { context, workspaceId, library, root, exactDocument };
  });
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  return <DomainFileCabinet slug={slug} context={result.value.context} initialLibrary={result.value.library} initialRoot={result.value.root} initialDocument={result.value.exactDocument} initialVersionId={versionId} />;
}

function one(value: string | string[] | undefined): string | null {
  return typeof value === "string" && value ? value : null;
}

function notFound(): ApiError {
  return new ApiError("Not found", 404, "not_found");
}
