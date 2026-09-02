import { redirect } from "next/navigation";

import { SetupPage } from "../../../features/identity/SetupPage";
import type { SetupStatus } from "../../../features/identity/api";
import { serverApiRequest } from "../../../shared/api/server-client";

export default async function SetupRoute() {
  const status = await serverApiRequest<SetupStatus>("/api/v1/setup/status");
  if (!status.setup_required) redirect("/login");
  return <SetupPage />;
}
