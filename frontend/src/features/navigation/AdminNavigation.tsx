import Link from "next/link";

import type { SessionUser } from "../../platform/identity/session";

export function AdminNavigation({ user }: { user: SessionUser }) {
  return (
    <header className="area-navigation admin-navigation">
      <Link className="area-brand" href="/admin/rag/models">AI Workshop Admin</Link>
      <nav aria-label="관리자 운영">
        <Link href="/admin/rag/models">RAG 모델</Link>
        <Link href="/app/workspaces">사용자 작업소</Link>
      </nav>
      <span>{user.display_name}</span>
    </header>
  );
}
