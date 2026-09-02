import { DocumentPage } from "../../../../../../features/assets/DocumentPage";
import type { DocumentSummary } from "../../../../../../features/assets/api";
import { serverApiRequest } from "../../../../../../shared/api/server-client";
import { incomingCookieHeader } from "../../../../../../shared/auth/server-session";

interface DocumentsRouteProps {
  params: Promise<{ workspaceId: string }>;
}

export default async function DocumentsRoute({ params }: DocumentsRouteProps) {
  const { workspaceId } = await params;
  const documents = await serverApiRequest<DocumentSummary[]>(
    `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/documents`,
    {},
    await incomingCookieHeader(),
  );
  return <DocumentPage workspaceId={workspaceId} initialDocuments={documents} />;
}
