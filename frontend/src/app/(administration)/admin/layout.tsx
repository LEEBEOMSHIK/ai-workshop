import type { ReactNode } from "react";

import { AdminNavigation } from "../../../features/navigation/AdminNavigation";
import { requireOwner } from "../../../shared/auth/server-session";

export default async function AdminLayout({ children }: Readonly<{ children: ReactNode }>) {
  const user = await requireOwner("/admin/rag/models");
  return (
    <div className="application-area administration-area">
      <AdminNavigation user={user} />
      {children}
    </div>
  );
}
