import type { ReactNode } from "react";
import { headers } from "next/headers";

import { AdminNavigation } from "../../../features/navigation/AdminNavigation";
import { requireOwner } from "../../../shared/auth/server-session";
import { routes } from "../../../shared/routing/routes";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../shared/ui/ServerRouteFailure";

export default async function AdminLayout({ children }: Readonly<{ children: ReactNode }>) {
  const requestHeaders = await headers();
  const returnTo =
    requestHeaders.get("x-ai-workshop-return-to") ?? routes.adminRagModels;
  const session = await captureServerRoute(() => requireOwner(returnTo));
  if (!session.ok) return <ServerRouteFailure failure={session.failure} />;
  const user = session.value;
  return (
    <div className="application-area administration-area">
      <AdminNavigation user={user} />
      {children}
    </div>
  );
}
