import type { ReactNode } from "react";

import { WorkspaceNavigation } from "../../../features/navigation/WorkspaceNavigation";
import { requireWorkspaceUser } from "../../../shared/auth/server-session";

export default async function WorkspaceLayout({
  children,
}: Readonly<{ children: ReactNode }>) {
  const user = await requireWorkspaceUser("/app/workspaces");
  return (
    <div className="application-area">
      <WorkspaceNavigation user={user} />
      {children}
    </div>
  );
}
