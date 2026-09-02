import Link from "next/link";

import type { SessionUser } from "../../platform/identity/session";

export function WorkspaceNavigation({ user }: { user: SessionUser }) {
  return (
    <header className="area-navigation">
      <Link className="area-brand" href="/app/workspaces">AI Workshop</Link>
      <nav aria-label="사용자 작업소">
        <Link href="/app/workspaces">지식 공간</Link>
        <Link href="/app/rag/search">RAG 검색</Link>
        <Link href="/app/rag/configurations">RAG 구성</Link>
        {user.role === "owner" ? <Link href="/admin/rag/models">관리</Link> : null}
      </nav>
      <span>{user.display_name}</span>
    </header>
  );
}
