"use client";

import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../../shared/api/client";
import {
  type DeploymentOption,
  type FolderOption,
  type SavedConfiguration,
  type SearchOptions,
  type SearchRequest,
  type SearchResult,
  type SearchSubmissionContext,
  type WorkspaceOption,
  listSearchFolders,
  loadGenerationProcessingOptions,
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

const MAX_SEARCH_HISTORY_ITEMS = 20;

const providerLabels: Record<DeploymentOption["provider"], string> = {
  local_openai_compatible: "로컬 OpenAI 호환",
  openai_responses: "OpenAI Responses API",
};

const locationLabels: Record<DeploymentOption["location"], string> = {
  local: "로컬",
  on_premise: "사내 온프레미스",
  external: "외부 API",
};

export function SearchPage({ initialOptions }: { initialOptions?: SearchOptions }) {
  const [options, setOptions] = useState<SearchOptions>(
    initialOptions ?? { configurations: [], workspaces: [] },
  );
  const [processingOptionsLoading, setProcessingOptionsLoading] = useState(
    initialOptions?.generationProfiles === undefined || initialOptions?.deployments === undefined,
  );
  const [processingOptionsFailed, setProcessingOptionsFailed] = useState(false);
  const [processingDetailsOpen, setProcessingDetailsOpen] = useState(false);
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
          setOptions((current) => ({
            ...current,
            configurations: loaded.configurations,
            workspaces: loaded.workspaces,
          }));
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

  useEffect(() => {
    if (
      initialOptions?.generationProfiles !== undefined && initialOptions.deployments !== undefined
    ) return;
    let active = true;
    loadGenerationProcessingOptions({
      generationProfiles: initialOptions?.generationProfiles,
      deployments: initialOptions?.deployments,
    })
      .then((loaded) => {
        if (!active) return;
        setOptions((current) => ({ ...current, ...loaded }));
        setProcessingOptionsFailed(false);
      })
      .catch(() => {
        if (active) setProcessingOptionsFailed(true);
      })
      .finally(() => {
        if (active) setProcessingOptionsLoading(false);
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
  const selectedGenerationProfile = options.generationProfiles?.find(
    (profile) => profile.id === selectedConfiguration?.generation_profile_id,
  );
  const selectedDeployment = options.deployments?.find(
    (deployment) => deployment.deployment_version_id === selectedGenerationProfile?.deployment_version_id,
  );
  const generationRequested = selectedConfiguration?.answer_policy.mode === "generative";
  const selectedProcessingKnown = !generationRequested || selectedDeployment !== undefined;
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
      !selectedProcessingKnown ||
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
    const history: SearchRequest["history"] = completedSearches
      .flatMap(({ result, context }) => {
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
      })
      .slice(-MAX_SEARCH_HISTORY_ITEMS);
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
                setProcessingDetailsOpen(false);
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
          {selectedConfiguration ? (
            <ProcessingDisclosure
              configuration={selectedConfiguration}
              deployment={selectedDeployment}
              loading={processingOptionsLoading}
              failed={processingOptionsFailed}
              detailsOpen={processingDetailsOpen}
              onToggleDetails={() => setProcessingDetailsOpen((current) => !current)}
            />
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
              !selectedProcessingKnown ||
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

function ProcessingDisclosure({
  configuration,
  deployment,
  loading,
  failed,
  detailsOpen,
  onToggleDetails,
}: {
  configuration: SavedConfiguration;
  deployment: DeploymentOption | undefined;
  loading: boolean;
  failed: boolean;
  detailsOpen: boolean;
  onToggleDetails: () => void;
}) {
  if (configuration.answer_policy.mode !== "generative") {
    return (
      <aside className="processing-disclosure" aria-label="선택한 구성 처리 안내">
        <p role="status" aria-label="선택한 구성 처리 안내">
          LLM 생성을 요청하지 않는 추출식 구성입니다. 검색된 원문 근거를 그대로 제공합니다.
        </p>
      </aside>
    );
  }
  if (!deployment) {
    const message = loading
      ? "선택한 구성의 모델 및 처리 위치를 확인하는 중입니다."
      : safeProcessingUnavailableMessage(configuration.answer_reasons, failed);
    return (
      <aside className="processing-disclosure" aria-label="선택한 구성 처리 안내">
        <p role="status" aria-label="선택한 구성 처리 안내">{message}</p>
      </aside>
    );
  }
  return (
    <aside className="processing-disclosure" aria-label="선택한 구성 처리 안내">
      <p role="status" aria-label="선택한 구성 처리 안내">{deployment.approval.disclosure}</p>
      <button
        type="button"
        className="processing-details-toggle"
        aria-expanded={detailsOpen}
        aria-controls="selected-processing-details"
        onClick={onToggleDetails}
      >
        모델 및 처리 위치 상세
      </button>
      {detailsOpen ? (
        <div id="selected-processing-details" role="region" aria-label="모델 및 처리 위치 상세">
          <dl className="identity-list">
            <div><dt>실행 배포</dt><dd>{deployment.display_name}</dd></div>
            <div><dt>Model Definition</dt><dd>{deployment.model_name} v{deployment.model_version}</dd></div>
            <div><dt>공급자</dt><dd>{providerLabels[deployment.provider]}</dd></div>
            <div><dt>Provider 모델 ID</dt><dd>{deployment.provider_model_id}</dd></div>
            <div><dt>처리 위치</dt><dd>{locationLabels[deployment.location]}</dd></div>
            <div><dt>외부 전송</dt><dd>{deployment.external_transfer ? "외부 전송 대상" : "외부 전송 없음"}</dd></div>
          </dl>
        </div>
      ) : null}
    </aside>
  );
}

function safeProcessingUnavailableMessage(reasonCodes: string[], failed: boolean): string {
  const messages: Record<string, string> = {
    deployment_not_allowed_in_environment: "현재 환경에서는 선택한 생성 실행을 사용할 수 없습니다.",
    workspace_external_transfer_denied: "지식 공간 정책에서 외부 전송을 허용하지 않습니다.",
    provider_not_allowed: "회사 정책에서 선택한 외부 생성 서비스를 허용하지 않습니다.",
    deployment_not_ready: "선택한 생성 실행의 준비 상태를 확인해 주세요.",
    provider_authentication_failed: "생성 서비스 인증 상태를 확인해 주세요.",
    provider_rate_limited: "생성 서비스 요청 한도를 확인해 주세요.",
    provider_timeout: "생성 서비스 응답 시간이 초과되었습니다.",
    provider_invalid_response: "생성 서비스 응답 상태를 확인해 주세요.",
  };
  const known = reasonCodes.map((code) => messages[code]).find(Boolean);
  if (known) return known;
  return failed
    ? "선택한 구성의 모델 및 처리 위치를 불러오지 못했습니다."
    : "선택한 구성의 모델 및 처리 위치를 확인할 수 없습니다.";
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
  const generationMessages: Record<string, string> = {
    deployment_not_allowed_in_environment: "현재 환경에서는 선택한 생성 실행을 사용할 수 없습니다.",
    workspace_external_transfer_denied: "선택한 지식 공간의 외부 전송 정책이 생성을 허용하지 않습니다.",
    provider_not_allowed: "현재 데이터 정책이 선택한 외부 생성 서비스를 허용하지 않습니다.",
    deployment_not_ready: "선택한 생성 실행이 준비되지 않았습니다.",
    provider_authentication_failed: "생성 서비스 인증 상태를 확인해 주세요.",
    provider_rate_limited: "생성 서비스 요청 한도에 도달했습니다.",
    provider_timeout: "생성 서비스 응답 시간이 초과되었습니다.",
    provider_invalid_response: "생성 서비스가 유효한 응답을 반환하지 않았습니다.",
    structured_output_invalid: "생성 서비스의 구조화 응답을 확인할 수 없습니다.",
    citation_validation_failed: "생성 답변의 근거 인용을 확인할 수 없습니다.",
  };
  if (generationMessages[error.code]) return generationMessages[error.code];
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
