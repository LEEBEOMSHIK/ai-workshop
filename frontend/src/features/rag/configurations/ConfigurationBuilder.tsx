import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";

import { ApiError } from "../../../shared/api/client";
import type {
  ModelDefinition,
  Profile,
  SavedConfiguration,
  SavedConfigurationCreate,
  Workspace,
} from "./api";
import { saveConfiguration } from "./api";
import {
  hasResolvableEmbedding,
  hasResolvableGeneration,
  generationOptionLabel,
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
    () => profiles.filter((profile) => hasResolvableGeneration(profile, models)),
    [models, profiles],
  );
  const [answerMode, setAnswerMode] = useState<"extractive" | "generative">("extractive");
  const [generationProfileId, setGenerationProfileId] = useState("");
  const [name, setName] = useState("");
  const [workspaceIds, setWorkspaceIds] = useState<string[]>([]);
  const [minSemanticScore, setMinSemanticScore] = useState(0.7);
  const [minKeywordCoverage, setMinKeywordCoverage] = useState(0.5);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const operation = useRef(0);
  const controller = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      operation.current += 1;
      controller.current?.abort();
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
  const effectiveGenerationProfileId = generationProfiles.some(
    (profile) => profile.id === generationProfileId,
  )
    ? generationProfileId
    : generationProfiles[0]?.id ?? "";
  const generationProfile = generationProfiles.find(
    (profile) => profile.id === effectiveGenerationProfileId,
  );
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
              onChange={(event) => setAnswerMode(event.target.value as "extractive" | "generative")}
            >
              <option value="extractive">추출식 기준선</option>
              <option value="generative" disabled={generationProfiles.length === 0}>
                근거 제한 LLM 생성
              </option>
            </select>
          </label>
          {answerMode === "generative" ? (
            <label>
              Generation Profile
              <select
                value={effectiveGenerationProfileId}
                onChange={(event) => setGenerationProfileId(event.target.value)}
              >
                {generationProfiles.map((profile) => (
                  <option key={profile.id} value={profile.id}>
                    {generationOptionLabel(profile, models)}
                  </option>
                ))}
              </select>
            </label>
          ) : null}
          <ReadOnlyComponent
            label="Answer Policy"
            value={`${answerMode} · complete provenance · separate sources`}
          />
          <ReadOnlyComponent label="LLM" value={packageSummary.llm} />
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
                  onChange={(event) => setWorkspaceIds((current) =>
                    event.target.checked
                      ? [...current, workspace.id]
                      : current.filter((id) => id !== workspace.id),
                  )}
                />
                {workspace.name}
              </label>
            ))}
          </div>
          {workspaces.length === 0 ? <p role="status">선택할 수 있는 지식 공간이 없습니다.</p> : null}
        </fieldset>

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
