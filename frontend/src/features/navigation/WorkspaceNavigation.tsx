import Link from "next/link";

import type { SessionUser } from "../identity/session";
import { routes } from "../../shared/routing/routes";

export function WorkspaceNavigation({ user }: { user: SessionUser }) {
  return (
    <header className="area-navigation">
      <Link className="area-brand" href={routes.workshopHome}>AI Workshop</Link>
      <nav aria-label="비공개 작업소">
        <Link href={routes.workshopHome}>지식 공간</Link>
        <Link href={routes.workshopRagSearch}>RAG 검색</Link>
        <Link href={routes.labs}>AI Lab</Link>
        {user.role === "owner" ? <Link href={routes.adminRagModels}>관리</Link> : null}
      </nav>
      <span>{user.display_name}</span>
    </header>
  );
}
