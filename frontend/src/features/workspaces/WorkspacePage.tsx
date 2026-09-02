import Link from "next/link";

import type { WorkspaceKind, WorkspaceSummary } from "./api";

interface WorkspacePageProps {
  initialWorkspaces?: WorkspaceSummary[];
}

const labels: Record<WorkspaceKind, string> = {
  company: "전사",
  team: "팀",
  personal: "개인",
  temporary: "임시",
};

export function WorkspacePage({ initialWorkspaces = [] }: WorkspacePageProps) {
  return (
    <main className="workspace-shell">
      <header className="workspace-header">
        <div>
          <p className="eyebrow">KNOWLEDGE SPACES</p>
          <h1 className="workspace-title">문서가 머무는 곳</h1>
        </div>
        <label className="workspace-kind">
          새 공간 유형
          <select defaultValue="temporary">
            <option value="company">전사</option>
            <option value="personal">개인</option>
            <option value="temporary">임시</option>
          </select>
        </label>
      </header>
      <section className="workspace-list" aria-label="지식 공간 목록">
        {initialWorkspaces.map((workspace) => (
          <Link
            className="workspace-row"
            href={`/app/workspaces/${workspace.id}/documents`}
            key={workspace.id}
          >
            <span className={`workspace-badge ${workspace.kind}`}>
              {labels[workspace.kind]}
            </span>
            <div>
              <h2>{workspace.name}</h2>
              <p>{workspace.expires_at ? "만료 일정 있음" : "지속 보관"}</p>
            </div>
          </Link>
        ))}
      </section>
    </main>
  );
}
