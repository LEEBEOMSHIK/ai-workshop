"use client";

import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../../shared/api/client";
import {
  type FolderOption,
  type SavedConfiguration,
  type SearchOptions,
  type SearchRequest,
  type SearchResult,
  type SearchSubmissionContext,
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

export function SearchPage({ initialOptions }: { initialOptions?: SearchOptions }) {
  const [options, setOptions] = useState<SearchOptions>(
    initialOptions ?? { configurations: [], workspaces: [] },
  );
  const [folderOptions, setFolderOptions] = useState<Record<string, FolderOption[]>>({});
  const [workspaceIds, setWorkspaceIds] = useState<string[]>([]);
  const [folderIds, setFolderIds] = useState<string[]>([]);
  const [configurationId, setConfigurationId] = useState("");
  const [experimentalConsent, setExperimentalConsent] = useState(false);
  const [query, setQuery] = useState("");
  const [completedSearches, setCompletedSearches] = useState<Array<{
    result: SearchResult;
    context: SearchSubmissionContext;
  }>>([]);
  const [loading, setLoading] = useState(initialOptions === undefined);
  const [optionsLoadFailed, setOptionsLoadFailed] = useState(false);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const requestGeneration = useRef(0);
  const searchController = useRef<AbortController | null>(null);

  useEffect(() => {
    if (initialOptions !== undefined) return;
    let active = true;
    loadSearchOptions()
      .then((loaded) => {
        if (active) {
          setOptions(loaded);
          setOptionsLoadFailed(false);
        }
      })
      .catch((caught: unknown) => {
        if (active) {
          setOptionsLoadFailed(true);
          setError(searchOptionsErrorMessage(caught));
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [initialOptions]);

  useEffect(
    () => () => {
      requestGeneration.current += 1;
      searchController.current?.abort();
    },
    [],
  );

  const workspaceNames = useMemo(
    () => new Map(options.workspaces.map((workspace) => [workspace.id, workspace.name])),
    [options.workspaces],
  );
  const selectedConfiguration = options.configurations.find(
    (configuration) => configuration.id === configurationId,
  );
  const requiresExperimentalConsent = selectedConfiguration?.experimental === true;
  const selectedConfigurationReady =
    selectedConfiguration?.search_ready === true &&
    selectedConfiguration.answer_ready === true &&
    selectedConfiguration.service_ready === true;
  const conversationLocked = completedSearches.length > 0;

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
    if (
      !selectedConfiguration ||
      workspaceIds.length === 0 ||
      query.trim().length < 2 ||
      !selectedConfigurationReady ||
      (requiresExperimentalConsent && !experimentalConsent)
    ) {
      return;
    }
    const submittedWorkspaces = workspaceIds.flatMap((workspaceId) => {
      const workspace = options.workspaces.find((candidate) => candidate.id === workspaceId);
      return workspace
        ? [{ id: workspace.id, name: workspace.name, kind: workspace.kind }]
        : [];
    });
    if (submittedWorkspaces.length !== workspaceIds.length) return;
    const submittedWorkspaceIds = new Set(workspaceIds);
    const submittedFolders = Object.entries(folderOptions).flatMap(([workspaceId, folders]) =>
      submittedWorkspaceIds.has(workspaceId)
        ? folders
            .filter((folder) => folderIds.includes(folder.id))
            .map((folder) => ({ id: folder.id, name: folder.name, workspaceId }))
        : [],
    );
    const experimental = requiresExperimentalConsent && experimentalConsent;
    const history: SearchRequest["history"] = completedSearches.flatMap(({ result, context }) => {
      const turns: SearchRequest["history"] = [
        { role: "user", content: context.query, turn_id: null, validation_token: null },
      ];
      if (
        result.generation?.status === "answered" &&
        result.generation.text &&
        result.generation.turn_id &&
        result.generation.validation_token
      ) {
        turns.push({
          role: "assistant",
          content: result.generation.text,
          turn_id: result.generation.turn_id,
          validation_token: result.generation.validation_token,
        });
      }
      return turns;
    });
    const context: SearchSubmissionContext = {
      query: query.trim(),
      configuration: {
        id: selectedConfiguration.id,
        versionId: selectedConfiguration.version_id,
        version: selectedConfiguration.version,
        name: selectedConfiguration.name,
        experimental: selectedConfiguration.experimental,
      },
      workspaces: submittedWorkspaces,
      folders: submittedFolders,
      experimentalConsent: experimental,
    };
    searchController.current?.abort();
    const controller = new AbortController();
    searchController.current = controller;
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    setError("");
    setSearching(true);
    try {
      const result = await searchEvidence(
        {
          query: context.query,
          configuration_id: context.configuration.id,
          workspace_ids: context.workspaces.map((workspace) => workspace.id),
          folder_ids: context.folders.map((folder) => folder.id),
          top_k: 10,
          experimental,
          history,
        },
        controller.signal,
      );
      if (requestGeneration.current === generation && !controller.signal.aborted) {
        setCompletedSearches((current) => [...current, { result, context }]);
        setQuery("");
      }
    } catch (caught) {
      if (requestGeneration.current === generation && !controller.signal.aborted) {
        setError(searchErrorMessage(caught));
      }
    } finally {
      if (requestGeneration.current === generation) {
        searchController.current = null;
        setSearching(false);
      }
    }
  }

  function cancelSearch() {
    requestGeneration.current += 1;
    searchController.current?.abort();
    searchController.current = null;
    setSearching(false);
  }

  function startNewConversation() {
    setCompletedSearches([]);
    setQuery("");
    setError("");
  }

  return (
    <main className="search-shell">
      <header className="search-header">
        <p className="eyebrow">EVIDENCE-FIRST RAG SEARCH</p>
        <h1 className="search-title">근거를 확인하는 AI 대화</h1>
        <p>첫 질문 전에 지식 공간과 RAG 구성을 선택하면 같은 대화에서 후속질문을 이어갈 수 있습니다.</p>
      </header>

      {loading ? <p role="status">검색 옵션을 불러오는 중…</p> : null}
      {error ? <p className="form-error" role="alert">{error}</p> : null}

      {!loading && !optionsLoadFailed ? (
        <form className="search-controls" onSubmit={handleSubmit}>
          <fieldset disabled={searching || conversationLocked}>
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
            <fieldset disabled={searching || conversationLocked}>
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
              disabled={searching || conversationLocked}
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
          {selectedConfiguration && !selectedConfigurationReady ? (
            <p role="status" aria-label="RAG 서비스 준비 상태">
              {!selectedConfiguration.search_ready
                ? "선택한 구성의 검색 색인이 아직 준비되지 않았습니다."
                : "선택한 구성의 LLM 답변이 아직 준비되지 않았습니다."}{" "}
              관리자 구성 화면에서 준비 상태와 원인을 확인해 주세요.
            </p>
          ) : null}
          {requiresExperimentalConsent ? (
            <aside className="experimental-consent" aria-label="실험 구성 안내">
              <p><span className="experimental-badge">실험</span> 평가가 끝나지 않은 구성입니다.</p>
              <label>
                <input
                  type="checkbox"
                  disabled={searching}
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
              disabled={searching}
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
              !selectedConfigurationReady ||
              query.trim().length < 2 ||
              (requiresExperimentalConsent && !experimentalConsent)
            }
          >
            {searching ? "답변 생성 중…" : "질문 보내기"}
          </button>
          {searching ? (
            <button type="button" className="secondary-button" onClick={cancelSearch}>
              검색 취소
            </button>
          ) : null}
        </form>
      ) : null}

      {completedSearches.length > 0 ? (
        <section className="conversation-results" aria-label="현재 대화">
          <p className="conversation-notice">현재 대화는 이 브라우저 화면에서만 유지됩니다.</p>
          {completedSearches.map((completedSearch, index) => (
            <article
              className="search-results"
              data-testid="submitted-search-result"
              key={completedSearch.result.generation?.turn_id ?? `${completedSearch.context.query}-${index}`}
            >
              <p className="submitted-query">
                <strong>나</strong> {completedSearch.context.query}
              </p>
              {completedSearch.result.resolved_query &&
              completedSearch.result.resolved_query !== completedSearch.context.query ? (
                <p className="resolved-query">
                  검색에 사용한 질의: {completedSearch.result.resolved_query}
                </p>
              ) : null}
              <EvidenceAnswer result={completedSearch.result} context={completedSearch.context} />
              <RelatedSources result={completedSearch.result} context={completedSearch.context} />
            </article>
          ))}
          <button type="button" className="secondary-button" onClick={startNewConversation}>
            새 대화
          </button>
        </section>
      ) : null}
    </main>
  );
}

function ConfigurationOption({ configuration }: { configuration: SavedConfiguration }) {
  return (
    <option value={configuration.id}>
      {configuration.name} v{configuration.version}
      {configuration.experimental ? " · 실험" : ""}
      {!configuration.search_ready ? " · 색인 준비 전" : ""}
      {configuration.search_ready && !configuration.answer_ready ? " · LLM 준비 전" : ""}
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

function searchOptionsErrorMessage(error: unknown): string {
  if (error instanceof ApiError && error.status === 401) return "로그인이 필요합니다.";
  return "검색 범위와 구성을 불러오지 못했습니다.";
}
