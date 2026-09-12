import type { SessionUser } from "../identity/session";
import { AreaNavigation } from "./AreaNavigation";

export function AdminNavigation({ user }: { user: SessionUser }) {
  return <AreaNavigation area="admin" user={user} />;
}
