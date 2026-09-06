import { RuntimeTopologyPage } from "../../../../../features/runtime-topology/RuntimeTopologyPage";
import type { RuntimeTopology } from "../../../../../features/runtime-topology/api";
import { serverApiRequest } from "../../../../../shared/api/server-client";
import {
  incomingCookieHeader,
  requireOwner,
} from "../../../../../shared/auth/server-session";
import { routes } from "../../../../../shared/routing/routes";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../../../shared/ui/ServerRouteFailure";

export default async function RuntimeTopologyRoute() {
  const result = await captureServerRoute(async () => {
    await requireOwner(routes.adminSystemRuntime);
    const cookieHeader = await incomingCookieHeader();
    return serverApiRequest<RuntimeTopology>(
      "/api/v1/admin/system/runtime-topology",
      {},
      cookieHeader,
    );
  });
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  return <RuntimeTopologyPage topology={result.value} />;
}
