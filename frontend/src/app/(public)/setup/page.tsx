import { redirect } from "next/navigation";

import { SetupPage } from "../../../features/identity/SetupPage";
import type { SetupStatus } from "../../../features/identity/api";
import { serverApiRequest } from "../../../shared/api/server-client";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../shared/ui/ServerRouteFailure";

export default async function SetupRoute() {
  const result = await captureServerRoute(() =>
    serverApiRequest<SetupStatus>("/api/v1/setup/status"),
  );
  if (!result.ok) return <ServerRouteFailure failure={result.failure} />;
  const status = result.value;
  if (!status.setup_required) redirect("/login");
  return <SetupPage />;
}
