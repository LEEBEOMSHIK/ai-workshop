"use client";

import Link from "next/link";
import { useState } from "react";

import { workspaceDocumentPath } from "../../shared/routing/routes";
import type { WorkspaceKind, WorkspaceSummary } from "./api";
import { WorkspaceCreateForm } from "./WorkspaceCreateForm";
import styles from "./WorkspacePage.module.css";

interface WorkspacePageProps {
  initialWorkspaces?: WorkspaceSummary[];
  canCreateCompany?: boolean;
}

const labels: Record<WorkspaceKind, string> = {
  company: "전사",
  team: "팀",
  personal: "개인",
  temporary: "임시",
};

export function WorkspacePage({ initialWorkspaces = [], canCreateCompany = false }: WorkspacePageProps) {
  const [workspaces, setWorkspaces] = useState(initialWorkspaces);
  const [creating, setCreating] = useState(false);
  const [selectedGroup, setSelectedGroup] = useState("전체 공간");
  const [query, setQuery] = useState("");
  const groups: { kinds: WorkspaceKind[]; label: string }[] = [
    { kinds: ["company", "team"], label: "회사 공간" },
    { kinds: ["personal"], label: "개인 공간" },
    { kinds: ["temporary"], label: "임시 공간" },
  ];
  const activeGroup = groups.find((group) => group.label === selectedGroup);
  const matchingWorkspaces = workspaces.filter((workspace) =>
    (!activeGroup || activeGroup.kinds.includes(workspace.kind)) &&
    workspace.name.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()),
  );
  return (
    <main className={styles.shell}>
      <header className={styles.header}>
        <div>
          <p className={styles.kicker}>FILE CABINET</p>
          <h1>파일함</h1>
          <p>공간을 열어 파일과 폴더를 탐색하고 원본과 버전을 관리합니다.</p>
        </div>
        <button type="button" aria-expanded={creating} onClick={() => setCreating((current) => !current)}>
          {creating ? "공간 만들기 닫기" : "공간 만들기"}
        </button>
      </header>
      {creating ? <WorkspaceCreateForm canCreateCompany={canCreateCompany} onCreated={(created) => setWorkspaces((current) => [...current.filter((workspace) => workspace.id !== created.id), created])} /> : null}
      <div className={styles.explorer}>
        <aside className={styles.sidebar} aria-label="공간 유형">
          <h2>보관 공간</h2>
          <button type="button" aria-pressed={selectedGroup === "전체 공간"} onClick={() => setSelectedGroup("전체 공간")}>
            <span>전체 공간</span>{" "}<span>{workspaces.length}</span>
          </button>
          {groups.map((group) => <button type="button" key={group.label} aria-pressed={selectedGroup === group.label} onClick={() => setSelectedGroup(group.label)}>
            <span>{group.label}</span>{" "}<span>{workspaces.filter((workspace) => group.kinds.includes(workspace.kind)).length}</span>
          </button>)}
          <p>접근 가능한 공간만 표시합니다.</p>
        </aside>
      <section className={styles.list} aria-label="지식 공간 목록">
        <div className={styles.listHeader}>
          <p>{selectedGroup} · {matchingWorkspaces.length}개 공간</p>
          <label className={styles.search}>공간 이름 검색
            <input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="공간 이름 입력" />
          </label>
        </div>
        {matchingWorkspaces.length === 0 ? <p className={styles.empty}>
          {query.trim() ? "검색한 이름과 일치하는 공간이 없습니다." : activeGroup ? `접근 가능한 ${activeGroup.label}이 없습니다.` : "접근 가능한 공간이 없습니다. 공간을 만들어 자료를 보관해 보세요."}
        </p> : null}
        {groups.map((group) => {
          const items = matchingWorkspaces.filter((workspace) => group.kinds.includes(workspace.kind));
          if (items.length === 0) return null;
          return <section className={styles.group} key={group.label}>
            <h2>{group.label}</h2>
            {items.map((workspace) => (
              <Link className={styles.row} href={workspaceDocumentPath(workspace.id)} key={workspace.id}>
                <span className={`${styles.badge} ${styles[workspace.kind]}`}>{labels[workspace.kind]}</span>
                <div>
                  <h3>{workspace.name}</h3>
                  <p>{workspace.expires_at ? "만료 일정 있음" : "지속 보관"}</p>
                </div>
                <span className={styles.open}>공간 열기 <span aria-hidden="true">→</span></span>
              </Link>
            ))}
          </section>;
        })}
      </section>
      </div>
    </main>
  );
}
