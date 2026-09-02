import Link from "next/link";

import { routes } from "../../shared/routing/routes";
import type { SessionUser } from "../identity/session";

export function AdminNavigation({ user }: { user: SessionUser }) {
  return (
    <header className="area-navigation admin-navigation">
      <Link className="area-brand" href={routes.adminRagModels}>AI Workshop Admin</Link>
      <nav aria-label="관리자 운영">
        <Link href={routes.adminRagConfigurations}>RAG 구성</Link>
        <Link href={routes.adminRagModels}>RAG 모델</Link>
        <Link href={routes.workshopHome}>비공개 작업소</Link>
      </nav>
      <span>{user.display_name}</span>
    </header>
  );
}
