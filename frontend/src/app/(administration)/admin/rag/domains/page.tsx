import { DomainAdminPage } from "../../../../../features/rag/domains/DomainAdminPage";
import type { Domain, DomainAdminData, DomainConnection } from "../../../../../features/rag/domains/api";
import type { SavedConfiguration, Workspace } from "../../../../../features/rag/configurations/api";
import { serverApiRequest } from "../../../../../shared/api/server-client";
import { incomingCookieHeader, requireOwner } from "../../../../../shared/auth/server-session";
import { routes } from "../../../../../shared/routing/routes";
import { captureServerRoute, ServerRouteFailure } from "../../../../../shared/ui/ServerRouteFailure";

export default async function RagDomainsAdminRoute() {
  const result = await captureServerRoute(async () => {
    await requireOwner(routes.adminRagDomains);
    const cookieHeader = await incomingCookieHeader();
    const domains = await serverApiRequest<Domain[]>("/api/v1/admin/rag/domains", {}, cookieHeader);
    const [configurations, workspaces, historyEntries] = await Promise.all([
      serverApiRequest<SavedConfiguration[]>("/api/v1/rag/configurations", {}, cookieHeader),
      serverApiRequest<Workspace[]>("/api/v1/workspaces", {}, cookieHeader),
      Promise.all(domains.map(async (domain) => [
        domain.id,
        await serverApiRequest<DomainConnection[]>(
          `/api/v1/admin/rag/domains/${encodeURIComponent(domain.id)}/connections`,
          {},
          cookieHeader,
        ),
      ] as const)),
    ]);
    return {
      domains,
      configurations,
      workspaces,
      histories: Object.fromEntries(historyEntries),
    } satisfies DomainAdminData;
  });
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  return <DomainAdminPage initialData={result.value} />;
}
