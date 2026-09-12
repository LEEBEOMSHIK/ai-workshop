import type { SessionUser } from "../identity/session";
import { AreaNavigation } from "./AreaNavigation";

export function WorkspaceNavigation({ user }: { user: SessionUser }) {
  return <AreaNavigation area="workspace" user={user} />;
}
