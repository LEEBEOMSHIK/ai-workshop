"use client";

import { type FormEvent, useMemo, useState } from "react";

import { ApiError } from "../../../shared/api/client";
import type { SavedConfiguration, Workspace } from "../configurations/api";
import {
  type AdminDomainView,
  type DomainAdminData,
  type DomainConnection,
  activateDomainConnection,
  adminListDomainView,
  adminMutationDomainView,
  createDomain,
  createDomainConnection,
  deactivateDomain,
  updateDomain,
} from "./api";

export function DomainAdminPage({ initialData }: { initialData: DomainAdminData }) {
  const [domains, setDomains] = useState(() => initialData.domains.map(adminListDomainView));
  const [histories, setHistories] = useState(initialData.histories);
  const [slug, setSlug] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function handleCreate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!slug.trim() || !displayName.trim()) return;
    setCreating(true);
    setError("");
    try {
      const created = await createDomain({
        slug: slug.trim(),
        display_name: displayName.trim(),
        description: description.trim(),
      });
      setDomains((current) => [...current, adminMutationDomainView(created)]);
      setHistories((current) => ({ ...current, [created.id]: [] }));
      setSlug("");
      setDisplayName("");
      setDescription("");
      setNotice("도메인을 등록했습니다. 서비스 연결 버전을 만든 뒤 활성화하세요.");
    } catch (caught) {
      setError(adminErrorMessage(caught));
    } finally {
      setCreating(false);
    }
  }

  function replaceDomain(updated: AdminDomainView) {
    setDomains((current) => current.map((domain) => domain.id === updated.id ? updated : domain));
  }

  return (
    <main className="domain-admin-shell">
      <header className="domain-admin-header">
        <p className="eyebrow">도메인 서비스 관리</p>
        <h1>RAG 도메인 관리</h1>
        <p>전문 도메인을 등록하고, 검증된 RAG 구성 버전과 허용 지식 공간을 불변 연결로 관리합니다.</p>
      </header>

      {error ? <p className="form-error" role="alert">{error}</p> : null}
      {notice ? <p className="form-success" role="status">{notice}</p> : null}

      <section className="domain-create-panel" aria-labelledby="domain-create-title">
        <h2 id="domain-create-title">새 도메인 등록</h2>
        <form onSubmit={handleCreate}>
          <label>도메인 주소<input value={slug} onChange={(event) => setSlug(event.target.value)} placeholder="예: asset-management" /></label>
          <label>표시 이름<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
          <label>설명<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
          <button type="submit" disabled={creating || !slug.trim() || !displayName.trim()}>도메인 등록</button>
        </form>
      </section>

      <section className="domain-admin-list" aria-label="등록된 도메인">
        {domains.length === 0 ? <p>등록된 도메인이 없습니다.</p> : null}
        {domains.map((domain) => (
          <DomainAdminCard
            key={domain.id}
            domain={domain}
            history={histories[domain.id] ?? []}
            configurations={initialData.configurations}
            workspaces={initialData.workspaces}
            onDomainChange={replaceDomain}
            onHistoryChange={(history) => setHistories((current) => ({ ...current, [domain.id]: history }))}
            onError={setError}
            onNotice={setNotice}
          />
        ))}
      </section>
    </main>
  );
}

function DomainAdminCard({
  domain,
  history,
  configurations,
  workspaces,
  onDomainChange,
  onHistoryChange,
  onError,
  onNotice,
}: {
  domain: AdminDomainView;
  history: DomainConnection[];
  configurations: SavedConfiguration[];
  workspaces: Workspace[];
  onDomainChange: (domain: AdminDomainView) => void;
  onHistoryChange: (history: DomainConnection[]) => void;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
}) {
  const [displayName, setDisplayName] = useState(domain.displayName);
  const [description, setDescription] = useState(domain.description);
  const [configurationVersionId, setConfigurationVersionId] = useState("");
  const [workspaceIds, setWorkspaceIds] = useState<string[]>([]);
  const [pending, setPending] = useState(false);
  const selectedConfiguration = configurations.find(
    (configuration) => configuration.version_id === configurationVersionId,
  );
  const workspaceNames = useMemo(
    () => new Map(workspaces.map((workspace) => [workspace.id, workspace.name])),
    [workspaces],
  );
  const scopedWorkspaces = selectedConfiguration
    ? workspaces.filter((workspace) => selectedConfiguration.workspace_ids.includes(workspace.id))
    : [];

  async function perform(action: () => Promise<void>) {
    setPending(true);
    onError("");
    onNotice("");
    try {
      await action();
    } catch (caught) {
      onError(adminErrorMessage(caught));
    } finally {
      setPending(false);
    }
  }

  return (
    <article className="domain-admin-card" aria-label={`${domain.displayName} 도메인`}>
      <header>
        <div><h2>{domain.displayName}</h2><p>주소: {domain.slug}</p></div>
        <span className="domain-state">{domain.activeConnectionVersionId ? "활성" : "비활성"}</span>
      </header>

      <form onSubmit={(event) => {
        event.preventDefault();
        void perform(async () => {
          const updated = await updateDomain(domain.id, {
            display_name: displayName.trim(),
            description: description.trim(),
          });
          onDomainChange(adminMutationDomainView(updated));
          onNotice("도메인 기본 정보를 저장했습니다.");
        });
      }}>
        <label>표시 이름<input value={displayName} onChange={(event) => setDisplayName(event.target.value)} /></label>
        <label>설명<textarea value={description} onChange={(event) => setDescription(event.target.value)} /></label>
        <button type="submit" disabled={pending || !displayName.trim()}>기본 정보 저장</button>
      </form>

      <section className="domain-connection-builder" aria-label="새 서비스 연결">
        <h3>새 연결 버전</h3>
        <label>
          연결할 RAG 구성
          <select value={configurationVersionId} onChange={(event) => {
            setConfigurationVersionId(event.target.value);
            setWorkspaceIds([]);
          }}>
            <option value="">구성을 선택하세요</option>
            {configurations.map((configuration) => (
              <option key={configuration.version_id} value={configuration.version_id}>
                {configuration.name} · 버전 {configuration.version}
              </option>
            ))}
          </select>
        </label>
        {selectedConfiguration ? (
          <fieldset>
            <legend>허용 지식 공간</legend>
            {scopedWorkspaces.length === 0 ? <p>이 구성에서 선택할 수 있는 지식 공간이 없습니다.</p> : null}
            {scopedWorkspaces.map((workspace) => (
              <label key={workspace.id}>
                <input
                  type="checkbox"
                  checked={workspaceIds.includes(workspace.id)}
                  onChange={(event) => setWorkspaceIds((current) => event.target.checked
                    ? [...current, workspace.id]
                    : current.filter((id) => id !== workspace.id))}
                />
                {workspace.name}
              </label>
            ))}
          </fieldset>
        ) : null}
        <button type="button" disabled={pending || !selectedConfiguration || workspaceIds.length === 0} onClick={() => {
          if (!selectedConfiguration) return;
          void perform(async () => {
            const updatedHistory = await createDomainConnection(domain.id, {
              configuration_version_id: selectedConfiguration.version_id,
              workspace_ids: workspaceIds,
            });
            onHistoryChange(updatedHistory);
            setConfigurationVersionId("");
            setWorkspaceIds([]);
            onNotice("새 불변 연결 버전을 만들었습니다. 검토 후 활성화하세요.");
          });
        }}>새 연결 버전 만들기</button>
      </section>

      <section className="domain-connection-history" aria-label="연결 버전 이력">
        <div className="section-heading-row">
          <h3>불변 연결 이력</h3>
          {domain.activeConnectionVersionId ? (
            <button type="button" className="secondary-button" disabled={pending} onClick={() => void perform(async () => {
              onDomainChange(adminMutationDomainView(await deactivateDomain(domain.id)));
              onNotice("도메인을 비활성화했습니다. 연결 이력은 보존됩니다.");
            })}>도메인 비활성화</button>
          ) : null}
        </div>
        {history.length === 0 ? <p>아직 연결 버전이 없습니다.</p> : null}
        {history.map((connection) => (
          <article key={connection.id} aria-label={`연결 버전 ${connection.version}`}>
            <header>
              <h4>연결 버전 {connection.version}</h4>
              {domain.activeConnectionVersionId === connection.id ? <span>현재 활성</span> : null}
            </header>
            <p>{connection.configuration_name} · 구성 버전 {connection.configuration_version}</p>
            <p>지식 공간: {connection.workspace_ids.map((id) => workspaceNames.get(id) ?? "현재 확인할 수 없음").join(", ")}</p>
            {domain.activeConnectionVersionId !== connection.id ? (
              <button type="button" disabled={pending} onClick={() => void perform(async () => {
                onDomainChange(adminMutationDomainView(await activateDomainConnection(domain.id, connection.id)));
                onNotice(`연결 버전 ${connection.version}을 활성화했습니다.`);
              })}>이 버전 활성화</button>
            ) : null}
          </article>
        ))}
      </section>
    </article>
  );
}

function adminErrorMessage(caught: unknown): string {
  if (caught instanceof ApiError) {
    if (caught.code === "owner_required") return "도메인 관리는 소유자만 할 수 있습니다.";
    if (caught.code === "configuration_not_evaluated") return "평가를 통과한 구성만 활성화할 수 있습니다.";
    if (caught.code === "generation_not_configured") return "생성형 답변 구성이 준비되지 않았습니다.";
    if (caught.code === "domain_not_ready") return "검색·생성 서비스 준비 상태를 확인해 주세요.";
  }
  return "도메인 변경을 완료하지 못했습니다. 잠시 후 다시 시도해 주세요.";
}
