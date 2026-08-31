import { type FormEvent, useEffect, useMemo, useState } from "react";

import { ApiError } from "../../../shared/api/client";
import {
  type FolderOption,
  type SavedConfiguration,
  type SearchOptions,
  type SearchResult,
  type WorkspaceOption,
  listSearchFolders,
  loadSearchOptions,
  searchEvidence,
} from "./api";
import { EvidenceAnswer } from "./EvidenceAnswer";
import { RelatedSources } from "./RelatedSources";

const workspaceKindLabels: Record<WorkspaceOption["kind"], string> = {
  company: "전사",
  team: "팀",
  personal: "개인",
  temporary: "임시",
};

export function SearchPage() {
  const [options, setOptions] = useState<SearchOptions>({ configurations: [], workspaces: [] });
  const [folderOptions, setFolderOptions] = useState<Record<string, FolderOption[]>>({});
  const [workspaceIds, setWorkspaceIds] = useState<string[]>([]);
  const [folderIds, setFolderIds] = useState<string[]>([]);
  const [configurationId, setConfigurationId] = useState("");
  const [experimentalConsent, setExperimentalConsent] = useState(false);
  const [query, setQuery] = useState("");
  const [result, setResult] = useState<SearchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    loadSearchOptions()
      .then((loaded) => {
        if (active) setOptions(loaded);
      })
      .catch(() => {
        if (active) setError("검색 범위와 구성을 불러오지 못했습니다.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const workspaceNames = useMemo(
    () => new Map(options.workspaces.map((workspace) => [workspace.id, workspace.name])),
    [options.workspaces],
  );
  const selectedConfiguration = options.configurations.find(
    (configuration) => configuration.id === configurationId,
  );
  const requiresExperimentalConsent = selectedConfiguration?.experimental === true;

  async function toggleWorkspace(workspaceId: string, selected: boolean) {
    if (selected) {
      setWorkspaceIds((current) => [...current, workspaceId]);
      try {
        const folders = await listSearchFolders(workspaceId);
        setFolderOptions((current) => ({ ...current, [workspaceId]: folders }));
      } catch {
        setError("선택한 지식 공간의 폴더를 불러오지 못했습니다.");
      }
      return;
    }
    setWorkspaceIds((current) => current.filter((id) => id !== workspaceId));
    const removedFolderIds = new Set((folderOptions[workspaceId] ?? []).map((folder) => folder.id));
    setFolderIds((current) => current.filter((id) => !removedFolderIds.has(id)));
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!configurationId || workspaceIds.length === 0 || query.trim().length < 2) return;
    setError("");
    setSearching(true);
    try {
      setResult(
        await searchEvidence({
          query: query.trim(),
          configuration_id: configurationId,
          workspace_ids: workspaceIds,
          folder_ids: folderIds,
          top_k: 10,
          experimental: requiresExperimentalConsent && experimentalConsent,
        }),
      );
    } catch (caught) {
      setResult(null);
      setError(searchErrorMessage(caught));
    } finally {
      setSearching(false);
    }
  }

  return (
    <main className="search-shell">
      <header className="search-header">
        <p className="eyebrow">EVIDENCE-FIRST RAG SEARCH</p>
        <h1 className="search-title">근거부터 확인하는 검색</h1>
        <p>검색할 지식 공간과 저장된 구성을 직접 선택해 주세요.</p>
      </header>

      {loading ? <p role="status">검색 옵션을 불러오는 중…</p> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}

      {!loading ? (
        <form className="search-controls" onSubmit={handleSubmit}>
          <fieldset>
            <legend>검색할 지식 공간</legend>
            {options.workspaces.length === 0 ? (
              <p role="status">검색할 수 있는 지식 공간이 없습니다.</p>
            ) : null}
            {options.workspaces.map((workspace) => (
              <label key={workspace.id}>
                <input
                  type="checkbox"
                  checked={workspaceIds.includes(workspace.id)}
                  onChange={(event) => void toggleWorkspace(workspace.id, event.target.checked)}
                />
                <span className={`workspace-badge ${workspace.kind}`}>
                  {workspaceKindLabels[workspace.kind]}
                </span>
                {workspace.name}
              </label>
            ))}
          </fieldset>

          {workspaceIds.some((id) => (folderOptions[id] ?? []).length > 0) ? (
            <fieldset>
              <legend>폴더 (선택 사항)</legend>
              {workspaceIds.flatMap((workspaceId) =>
                (folderOptions[workspaceId] ?? []).map((folder) => (
                  <label key={folder.id}>
                    <input
                      type="checkbox"
                      checked={folderIds.includes(folder.id)}
                      onChange={(event) =>
                        setFolderIds((current) =>
                          event.target.checked
                            ? [...current, folder.id]
                            : current.filter((id) => id !== folder.id),
                        )
                      }
                    />
                    {workspaceNames.get(workspaceId)} / {folder.name}
                  </label>
                )),
              )}
            </fieldset>
          ) : null}

          <label>
            저장된 RAG 구성
            <select
              value={configurationId}
              onChange={(event) => {
                setConfigurationId(event.target.value);
                setExperimentalConsent(false);
              }}
            >
              <option value="">구성을 선택하세요</option>
              {options.configurations.map((configuration) => (
                <ConfigurationOption key={configuration.id} configuration={configuration} />
              ))}
            </select>
          </label>
          {options.configurations.length === 0 ? (
            <p role="status">사용할 수 있는 저장 구성이 없습니다.</p>
          ) : null}
          {requiresExperimentalConsent ? (
            <aside className="experimental-consent" aria-label="실험 구성 안내">
              <p><span className="experimental-badge">실험</span> 평가가 끝나지 않은 구성입니다.</p>
              <label>
                <input
                  type="checkbox"
                  checked={experimentalConsent}
                  onChange={(event) => setExperimentalConsent(event.target.checked)}
                />
                평가 전 구성을 실험 검색에 사용
              </label>
            </aside>
          ) : null}
          <label>
            검색 질문
            <input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
          <button
            type="submit"
            disabled={
              searching ||
              workspaceIds.length === 0 ||
              !configurationId ||
              query.trim().length < 2 ||
              (requiresExperimentalConsent && !experimentalConsent)
            }
          >
            {searching ? "검색 중…" : "근거 검색"}
          </button>
        </form>
      ) : null}

      {result ? (
        <div className="search-results">
          <EvidenceAnswer result={result} workspaceNames={workspaceNames} />
          <RelatedSources sources={result.related_sources} workspaceNames={workspaceNames} />
        </div>
      ) : null}
    </main>
  );
}

function ConfigurationOption({ configuration }: { configuration: SavedConfiguration }) {
  return (
    <option value={configuration.id}>
      {configuration.name} v{configuration.version}
      {configuration.experimental ? " · 실험" : ""}
    </option>
  );
}

function searchErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "검색 요청을 완료하지 못했습니다.";
  if (error.status === 401) return "로그인이 필요합니다.";
  if (error.status === 404) return "검색 범위 또는 구성을 찾을 수 없습니다.";
  if (error.status === 409) return "선택한 검색 구성을 지금 사용할 수 없습니다.";
  if (error.status === 503) {
    return "검색 서비스가 일시적으로 준비되지 않았습니다. 잠시 후 다시 시도해 주세요.";
  }
  return "검색 요청을 완료하지 못했습니다.";
}
