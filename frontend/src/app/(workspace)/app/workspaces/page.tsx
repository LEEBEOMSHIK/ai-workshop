import { WorkspacePage } from "../../../../features/workspaces/WorkspacePage";
import type { WorkspaceSummary } from "../../../../features/workspaces/api";
import { serverApiRequest } from "../../../../shared/api/server-client";
import { incomingCookieHeader } from "../../../../shared/auth/server-session";

export default async function WorkspacesRoute() {
  const workspaces = await serverApiRequest<WorkspaceSummary[]>(
    "/api/v1/workspaces",
    {},
    await incomingCookieHeader(),
  );
  return <WorkspacePage initialWorkspaces={workspaces} />;
}
