import type { ReactNode } from "react";
import { headers } from "next/headers";

import { WorkspaceNavigation } from "../../../features/navigation/WorkspaceNavigation";
import { requireWorkspaceUser } from "../../../shared/auth/server-session";
import { routes } from "../../../shared/routing/routes";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../shared/ui/ServerRouteFailure";

export default async function WorkspaceLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  const requestHeaders = await headers();
  const returnTo =
    requestHeaders.get("x-ai-workshop-return-to") ?? routes.workshopHome;
  const session = await captureServerRoute(() => requireWorkspaceUser(returnTo));
  if (!session.ok) return <ServerRouteFailure failure={session.failure} />;
  const user = session.value;
  return (
    <div className="application-area">
      <WorkspaceNavigation user={user} />
      {children}
    </div>
  );
}
