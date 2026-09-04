import { type FormEvent, useEffect, useId, useMemo, useRef, useState } from "react";

import { ApiError } from "../../../shared/api/client";
import type {
  DeploymentOption,
  ModelDefinition,
  Profile,
  SavedConfiguration,
  SavedConfigurationCreate,
  Workspace,
} from "./api";
import { loadDeploymentOptions, saveConfiguration } from "./api";
import {
  hasResolvableEmbedding,
  indexingOptionLabel,
  isV1CompatibleRetrieval,
  summarizeRagPackage,
} from "./packageSummary";

interface ConfigurationBuilderProps {
  configurations: SavedConfiguration[];
  models: ModelDefinition[];
  profiles: Profile[];
  workspaces: Workspace[];
  onSaved: (configuration: SavedConfiguration, addToComparison: boolean) => void;
}

export function ConfigurationBuilder({
  configurations,
  models,
  profiles,
  workspaces,
  onSaved,
}: ConfigurationBuilderProps) {
  const indexingProfiles = useMemo(
    () => profiles.filter((profile) => hasResolvableEmbedding(profile, models)),
    [models, profiles],
  );
  const baselineIndexingId =
    configurations.find((configuration) => configuration.is_system)?.indexing_profile_id ??
    indexingProfiles[0]?.id ??
    "";
  const [indexingProfileId, setIndexingProfileId] = useState(baselineIndexingId);
  const compatibleRetrievalProfiles = useMemo(
    () => profiles
      .filter((profile) => profile.kind === "retrieval")
      .filter((profile) => profileIndexingId(profile) === indexingProfileId)
      .filter(isV1CompatibleRetrieval)
      .sort((left, right) => Number(hasDense(right)) - Number(hasDense(left))),
    [indexingProfileId, profiles],
  );
  const [retrievalProfileId, setRetrievalProfileId] = useState(
    compatibleRetrievalProfiles[0]?.id ?? "",
  );
  const generationProfiles = useMemo(
    () => profiles.filter((profile) =>
      profile.kind === "generation"
      && !profile.legacy
      && Boolean(profile.deployment_version_id),
    ),
    [profiles],
  );
  const [answerMode, setAnswerMode] = useState<"extractive" | "generative">("extractive");
  const [generationProfileId, setGenerationProfileId] = useState("");
  const [deploymentOptions, setDeploymentOptions] = useState<DeploymentOption[]>([]);
  const [deploymentOptionsState, setDeploymentOptionsState] = useState<"idle" | "loading" | "loaded" | "error">("idle");
  const [externalApproved, setExternalApproved] = useState(false);
  const [name, setName] = useState("");
  const [workspaceIds, setWorkspaceIds] = useState<string[]>([]);
  const [minSemanticScore, setMinSemanticScore] = useState(0.7);
  const [minKeywordCoverage, setMinKeywordCoverage] = useState(0.5);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const operation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const deploymentController = useRef<AbortController | null>(null);
  const externalDisclosureId = useId();
  const externalTransferDetailsId = useId();

  useEffect(
    () => () => {
      operation.current += 1;
      controller.current?.abort();
      deploymentController.current?.abort();
    },
    [],
  );

  const effectiveRetrievalProfileId = compatibleRetrievalProfiles.some(
    (profile) => profile.id === retrievalProfileId,
  )
    ? retrievalProfileId
    : compatibleRetrievalProfiles[0]?.id ?? "";
  const indexingProfile = indexingProfiles.find((profile) => profile.id === indexingProfileId);
  const retrievalProfile = compatibleRetrievalProfiles.find(
    (profile) => profile.id === effectiveRetrievalProfileId,
  );

  function loadGenerationDeploymentOptions() {
    deploymentController.current?.abort();
    const nextController = new AbortController();
    deploymentController.current = nextController;
    setDeploymentOptionsState("loading");
    void loadDeploymentOptions(nextController.signal)
      .then((options) => {
        if (deploymentController.current !== nextController || nextController.signal.aborted) return;
        setDeploymentOptions(options.filter((item) =>
          item.provider === "local_openai_compatible" || item.provider === "openai_responses",
        ));
        setDeploymentOptionsState("loaded");
      })
      .catch(() => {
        if (deploymentController.current === nextController && !nextController.signal.aborted) {
          setDeploymentOptionsState("error");
        }
      })
      .finally(() => {
        if (deploymentController.current === nextController) {
          deploymentController.current = null;
        }
      });
  }

  function handleAnswerModeChange(mode: "extractive" | "generative") {
    setAnswerMode(mode);
    setExternalApproved(false);
    if (mode === "generative" && deploymentOptionsState === "idle") {
      loadGenerationDeploymentOptions();
    }
    if (mode === "extractive") {
      deploymentController.current?.abort();
      deploymentController.current = null;
      if (deploymentOptionsState === "loading") setDeploymentOptionsState("idle");
    }
  }
  const effectiveGenerationProfileId = generationProfiles.some(
    (profile) => profile.id === generationProfileId,
  )
    ? generationProfileId
    : generationProfiles[0]?.id ?? "";
  const generationProfile = generationProfiles.find(
    (profile) => profile.id === effectiveGenerationProfileId,
  );
  const generationDeployment = deploymentOptions.find(
    (option) => option.deployment_version_id === generationProfile?.deployment_version_id,
  );
  const externalApproval = generationDeployment?.external_transfer
    ? externalApprovalPayload(generationDeployment)
    : null;
  const packageSummary = summarizeRagPackage({
    indexing: indexingProfile,
    retrieval: retrievalProfile,
    generation: answerMode === "generative" ? generationProfile : undefined,
    models,
  });
  const requiresNewIndex = Boolean(
    baselineIndexingId && indexingProfileId && baselineIndexingId !== indexingProfileId,
  );
  const canSave = Boolean(
    name.trim() &&
      indexingProfileId &&
      effectiveRetrievalProfileId &&
      workspaceIds.length > 0 &&
      (answerMode === "extractive" || effectiveGenerationProfileId) &&
      (answerMode === "extractive" || generationDeployment?.readiness.ready) &&
      (answerMode === "extractive"
        || !generationDeployment?.external_transfer
        || (externalApproved && externalApproval !== null)) &&
      !saving,
  );

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!canSave) return;
    const submitter = (event.nativeEvent as SubmitEvent).submitter;
    const addToComparison =
      submitter instanceof HTMLButtonElement && submitter.value === "compare";
    const request: SavedConfigurationCreate = {
      name: name.trim(),
      indexing_profile_id: indexingProfileId,
      retrieval_profile_id: effectiveRetrievalProfileId,
      generation_profile_id:
        answerMode === "generative" ? effectiveGenerationProfileId : null,
      answer_policy: {
        mode: answerMode,
        min_semantic_score: minSemanticScore,
        min_keyword_coverage: minKeywordCoverage,
        require_complete_provenance: true,
        conflict_mode: "separate_sources",
      },
      workspace_ids: workspaceIds,
      ...(answerMode === "generative" && externalApproval && externalApproved
        ? {
            external_transfer_approval: externalApproval,
          }
        : {}),
    };
    controller.current?.abort();
    const nextController = new AbortController();
    controller.current = nextController;
    const generation = operation.current + 1;
    operation.current = generation;
    setSaving(true);
    setError("");
    try {
      const saved = await saveConfiguration(request, nextController.signal);
      if (operation.current !== generation || nextController.signal.aborted) return;
      onSaved(saved, addToComparison);
      setName("");
      setWorkspaceIds([]);
    } catch (caught) {
      if (operation.current === generation && !nextController.signal.aborted) {
        setError(configurationErrorMessage(caught));
      }
    } finally {
      if (operation.current === generation) {
        controller.current = null;
        setSaving(false);
      }
    }
  }

  return (
    <section className="configuration-builder" aria-labelledby="configuration-builder-title">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">SERVER PROFILE COMPOSITION</p>
          <h2 id="configuration-builder-title">새 RAG 패키지 구성</h2>
        </div>
        <p>저장 전 초안은 검색이나 평가 후보로 사용되지 않습니다.</p>
      </div>
      <form onSubmit={handleSubmit}>
        <fieldset disabled={saving}>
          <legend>색인 구성</legend>
          <label>
            색인 패키지
            <select
              value={indexingProfileId}
              onChange={(event) => setIndexingProfileId(event.target.value)}
            >
              {indexingProfiles.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {indexingOptionLabel(profile, models)}
                </option>
              ))}
            </select>
          </label>
          <p className="control-help">
            임베딩 모델과 청킹 방식이 함께 고정되며, 변경하면 호환되는 새 색인이 필요합니다.
          </p>
          <ReadOnlyComponent label="Parser" value={packageSummary.parser} />
          <ReadOnlyComponent label="Chunker" value={packageSummary.chunker} />
          <ReadOnlyComponent label="Embedding" value={packageSummary.embedding} />
          {requiresNewIndex ? (
            <p className="index-warning" role="alert">
              임베딩 또는 Indexing Profile이 변경되어 호환되는 새 색인 버전이 필요합니다.
            </p>
          ) : null}
        </fieldset>

        <fieldset disabled={saving}>
          <legend>검색 구성</legend>
          <label>
            Retrieval Profile
            <select
              value={effectiveRetrievalProfileId}
              onChange={(event) => setRetrievalProfileId(event.target.value)}
            >
              {compatibleRetrievalProfiles.map((profile) => (
                <option key={profile.id} value={profile.id}>
                  {profile.name} v{profile.version}
                </option>
              ))}
            </select>
          </label>
          <ReadOnlyComponent label="Sparse Retriever" value={packageSummary.sparseRetriever} />
          <ReadOnlyComponent
            label="Dense Retriever"
            value={packageSummary.denseRetriever}
          />
          <ReadOnlyComponent label="Fusion" value={packageSummary.fusion} />
          <ReadOnlyComponent label="Reranker" value={packageSummary.reranker} />
        </fieldset>

        <fieldset disabled={saving}>
          <legend>답변 구성</legend>
          <label>
            답변 방식
            <select
              value={answerMode}
              onChange={(event) => {
                handleAnswerModeChange(event.target.value as "extractive" | "generative");
              }}
            >
              <option value="extractive">추출식 기준선</option>
              <option value="generative" disabled={generationProfiles.length === 0}>
                근거 제한 LLM 생성
              </option>
            </select>
          </label>
          {answerMode === "generative" ? (
            <label>
              생성 구성
              <select
                value={effectiveGenerationProfileId}
                onChange={(event) => {
                  setGenerationProfileId(event.target.value);
                  setExternalApproved(false);
                }}
              >
                {generationProfiles.map((profile) => {
                  const deployment = deploymentOptions.find(
                    (option) => option.deployment_version_id === profile.deployment_version_id,
                  );
                  const disabled = !deployment?.readiness.ready;
                  return (
                    <option key={profile.id} value={profile.id} disabled={disabled}>
                      {generationDeploymentOptionLabel(profile, deployment)}
                    </option>
                  );
                })}
              </select>
            </label>
          ) : null}
          {answerMode === "generative" && deploymentOptionsState === "loading" ? (
            <p role="status">실행 가능한 생성 배포를 불러오는 중…</p>
          ) : null}
          {answerMode === "generative" && deploymentOptionsState === "error" ? (
            <div className="form-error" role="alert">
              <p>생성 배포 정보를 불러오지 못했습니다.</p>
              <button type="button" onClick={loadGenerationDeploymentOptions}>
                생성 배포 다시 불러오기
              </button>
            </div>
          ) : null}
          <ReadOnlyComponent
            label="Answer Policy"
            value={`${answerMode} · complete provenance · separate sources`}
          />
          <ReadOnlyComponent
            label="LLM"
            value={generationDeployment
              ? `${generationDeployment.model_name} v${generationDeployment.model_version}`
              : packageSummary.llm}
          />
          <label>
            최소 semantic score
            <input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={minSemanticScore}
              onChange={(event) => setMinSemanticScore(Number(event.target.value))}
            />
          </label>
          <label>
            최소 keyword coverage
            <input
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={minKeywordCoverage}
              onChange={(event) => setMinKeywordCoverage(Number(event.target.value))}
            />
          </label>
          {answerMode === "generative" ? (
            <p className="control-help">후속질문 문맥과 인용 검증 정책이 Generation Profile 버전에 함께 고정됩니다.</p>
          ) : null}
        </fieldset>

        <fieldset disabled={saving}>
          <legend>저장 정보</legend>
          <label>
            구성 이름
            <input value={name} onChange={(event) => setName(event.target.value)} required />
          </label>
          <div className="workspace-options" role="group" aria-label="적용할 지식 공간">
            {workspaces.map((workspace) => (
              <label key={workspace.id}>
                <input
                  type="checkbox"
                  value={workspace.id}
                  checked={workspaceIds.includes(workspace.id)}
                  onChange={(event) => {
                    setExternalApproved(false);
                    setWorkspaceIds((current) => event.target.checked
                      ? [...current, workspace.id]
                      : current.filter((id) => id !== workspace.id));
                  }}
                />
                {workspace.name}
              </label>
            ))}
          </div>
          {workspaces.length === 0 ? <p role="status">선택할 수 있는 지식 공간이 없습니다.</p> : null}
        </fieldset>

        {answerMode === "generative"
          && generationDeployment?.external_transfer
          && generationDeployment.approval?.required ? (
            <fieldset className="external-approval" disabled={saving}>
              <legend>외부 전송 확인</legend>
              <p id={externalDisclosureId}>{generationDeployment.approval.disclosure}</p>
              <p className="control-help" id={externalTransferDetailsId}>
                전송 범위: {transferCategoryLabels(generationDeployment.approval.transmitted_data_categories)}
                {" · "}고지 버전: {generationDeployment.approval.disclosure_version}
              </p>
              <label className="inline-check">
                <input
                  type="checkbox"
                  aria-describedby={`${externalDisclosureId} ${externalTransferDetailsId}`}
                  checked={externalApproved}
                  onChange={(event) => setExternalApproved(event.target.checked)}
                />
                {externalApprovalLabel(generationDeployment, workspaces, workspaceIds)}
              </label>
            </fieldset>
          ) : null}

        {error ? <p className="form-error" role="alert">{error}</p> : null}
        <div className="builder-actions">
          <button type="submit" value="save" disabled={!canSave}>
            {saving ? "저장 중…" : "저장"}
          </button>
          <button type="submit" value="compare" className="secondary-button" disabled={!canSave}>
            저장하고 비교에 추가
          </button>
        </div>
      </form>
    </section>
  );
}

function ReadOnlyComponent({ label, value }: { label: string; value: string }) {
  return <p className="component-summary"><strong>{label}</strong><span>{value}</span></p>;
}

function profileIndexingId(profile: Profile): string | null {
  const value = profile.config.indexing_profile_id;
  return typeof value === "string" ? value : null;
}

function hasConfigKey(profile: Profile | undefined, key: string): boolean {
  return Boolean(profile && key in profile.config && profile.config[key] !== null);
}

function hasDense(profile: Profile | undefined): boolean {
  return hasConfigKey(profile, "dense");
}

function configurationErrorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "RAG 구성을 저장하지 못했습니다.";
  if (error.status === 401) return "로그인이 필요합니다.";
  if (error.status === 404) return "선택한 지식 공간 또는 프로파일을 찾을 수 없습니다.";
  if (error.status === 409) return "같은 이름의 시스템 구성과 충돌합니다.";
  if (error.status === 422) return "구성 이름, 호환 프로파일, 답변 정책을 확인해 주세요.";
  if (error.status === 503) return "구성 저장 서비스를 잠시 사용할 수 없습니다.";
  return "RAG 구성을 저장하지 못했습니다.";
}

function generationDeploymentOptionLabel(
  profile: Profile,
  deployment: DeploymentOption | undefined,
): string {
  if (!deployment) return `${profile.name} v${profile.version} · 연결된 실행 배포 정보 없음`;
  const location = deployment.location === "external"
    ? "외부 API"
    : deployment.location === "on_premise" ? "사내 온프레미스" : "로컬";
  const reason = deployment.readiness.ready
    ? ""
    : ` · ${deployment.readiness.reason_codes.map(deploymentReasonLabel).join(", ")}`;
  return `${profile.name} v${profile.version} · ${deployment.display_name} · ${deployment.model_name} v${deployment.model_version} · ${deployment.provider_model_id} · ${location}${reason}`;
}

function deploymentReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    deployment_not_allowed_in_environment: "현재 환경에서 사용할 수 없음",
    workspace_external_transfer_denied: "지식 공간 정책에서 외부 전송을 허용하지 않음",
    provider_not_allowed: "회사 정책에서 외부 공급자를 허용하지 않음",
    deployment_not_ready: "실행 준비 확인 필요",
    provider_authentication_failed: "공급자 인증 확인 필요",
    provider_rate_limited: "공급자 요청 한도 초과",
    provider_timeout: "공급자 응답 시간 초과",
    provider_invalid_response: "공급자 응답 확인 필요",
  };
  return labels[reason] ?? "실행 준비 상태를 확인해 주세요";
}

function transferCategoryLabels(categories: string[]): string {
  const labels: Record<string, string> = {
    question: "현재 질문",
    bounded_history: "제한된 이전 대화",
    evidence: "선별된 문서 근거",
  };
  return categories.map((category) => labels[category] ?? category).join(", ");
}

function externalApprovalLabel(
  deployment: DeploymentOption,
  workspaces: Workspace[],
  workspaceIds: string[],
): string {
  const provider = deployment.provider === "openai_responses"
    ? "OpenAI Responses API"
    : "로컬 OpenAI 호환 공급자";
  const workspaceNames = workspaceIds
    .map((id) => workspaces.find((workspace) => workspace.id === id)?.name)
    .filter((name): name is string => Boolean(name));
  const categories = deployment.approval
    ? transferCategoryLabels(deployment.approval.transmitted_data_categories)
    : "전송 데이터";
  return `${provider}에 ${categories}를 전송하며, 선택한 지식 공간(${workspaceNames.join(", ") || "선택 전"})과 고지 ${deployment.approval?.disclosure_version ?? "현재 버전"} 내용을 확인했습니다.`;
}

function externalApprovalPayload(
  deployment: DeploymentOption,
): NonNullable<SavedConfigurationCreate["external_transfer_approval"]> | null {
  if (!deployment.approval.required) return null;
  return {
    confirmed: true,
    disclosure_version: deployment.approval.disclosure_version,
  };
}
