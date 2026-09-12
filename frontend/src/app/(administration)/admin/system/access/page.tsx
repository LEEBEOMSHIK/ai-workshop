import { AccessManagementPage } from "../../../../../features/identity/access/AccessManagementPage";
import { requireOwner } from "../../../../../shared/auth/server-session";
import { routes } from "../../../../../shared/routing/routes";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../../../shared/ui/ServerRouteFailure";

export default async function AccessManagementRoute() {
  const result = await captureServerRoute(() => requireOwner(routes.adminSystemAccess));
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  return <AccessManagementPage currentUser={result.value} />;
}
