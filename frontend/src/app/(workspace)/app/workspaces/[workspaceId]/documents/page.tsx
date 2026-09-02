import { DocumentPage } from "../../../../../../features/assets/DocumentPage";
import type { DocumentSummary } from "../../../../../../features/assets/api";
import { serverApiRequest } from "../../../../../../shared/api/server-client";
import {
  incomingCookieHeader,
  requireWorkspaceUser,
} from "../../../../../../shared/auth/server-session";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../../../../shared/ui/ServerRouteFailure";

interface DocumentsRouteProps {
  params: Promise<{ workspaceId: string }>;
}

export default async function DocumentsRoute({ params }: DocumentsRouteProps) {
  const { workspaceId } = await params;
  const result = await captureServerRoute(async () => {
    await requireWorkspaceUser(`/app/workspaces/${encodeURIComponent(workspaceId)}/documents`);
    return serverApiRequest<DocumentSummary[]>(
      `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/documents`,
      {},
      await incomingCookieHeader(),
    );
  });
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  return <DocumentPage workspaceId={workspaceId} initialDocuments={result.value} />;
}
