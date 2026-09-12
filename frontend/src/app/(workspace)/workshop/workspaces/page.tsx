import { WorkspacePage } from "../../../../features/workspaces/WorkspacePage";
import type { WorkspaceSummary } from "../../../../features/workspaces/api";
import { serverApiRequest } from "../../../../shared/api/server-client";
import {
  incomingCookieHeader,
  requireWorkspaceUser,
} from "../../../../shared/auth/server-session";
import { routes } from "../../../../shared/routing/routes";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../../shared/ui/ServerRouteFailure";

export default async function WorkspacesRoute() {
  const result = await captureServerRoute(async () => {
    const user = await requireWorkspaceUser(routes.workshopHome);
    const workspaces = await serverApiRequest<WorkspaceSummary[]>(
      "/api/v1/workspaces",
      {},
      await incomingCookieHeader(),
    );
    return { workspaces, canCreateCompany: user.role === "owner" };
  });
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  return <WorkspacePage initialWorkspaces={result.value.workspaces} canCreateCompany={result.value.canCreateCompany} />;
}
