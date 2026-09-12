import { DomainPickerPage } from "../../../../../features/rag/domains/DomainPickerPage";
import type { Domain } from "../../../../../features/rag/domains/api";
import { serverApiRequest } from "../../../../../shared/api/server-client";
import {
  incomingCookieHeader,
  requireWorkspaceUser,
} from "../../../../../shared/auth/server-session";
import { routes } from "../../../../../shared/routing/routes";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../../../shared/ui/ServerRouteFailure";

export default async function RagSearchRoute() {
  const result = await captureServerRoute(async () => {
    const user = await requireWorkspaceUser(routes.workshopRagSearch);
    const cookieHeader = await incomingCookieHeader();
    const domains = await serverApiRequest<Domain[]>("/api/v1/rag/domains", {}, cookieHeader);
    return { domains, isOwner: user.role === "owner" };
  });
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  return <DomainPickerPage domains={result.value.domains} isOwner={result.value.isOwner} />;
}
