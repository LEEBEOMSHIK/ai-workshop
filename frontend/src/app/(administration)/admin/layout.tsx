import type { ReactNode } from "react";

import { AdminNavigation } from "../../../features/navigation/AdminNavigation";
import { requireOwner } from "../../../shared/auth/server-session";
import {
  captureServerRoute,
  ServerRouteFailure,
} from "../../../shared/ui/ServerRouteFailure";

export default async function AdminLayout({ children }: Readonly<{ children: ReactNode }>) {
  const session = await captureServerRoute(() => requireOwner("/admin/rag/models"));
  if (!session.ok) return <ServerRouteFailure failure={session.failure} />;
  const user = session.value;
  return (
    <div className="application-area administration-area">
      <AdminNavigation user={user} />
      {children}
    </div>
  );
}
