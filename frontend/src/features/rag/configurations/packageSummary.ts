import type { ModelDefinition, Profile } from "./api";

export interface RagPackageSummary {
  parser: string;
  chunker: string;
  embedding: string;
  sparseRetriever: string;
  denseRetriever: string;
  fusion: string;
  reranker: string;
  llm: string;
}

export function summarizeRagPackage({
  indexing,
  retrieval,
  generation,
  models,
}: {
  indexing: Profile | undefined;
  retrieval: Profile | undefined;
  generation?: Profile | undefined;
  models: ModelDefinition[];
}): RagPackageSummary {
  const embedding = boundModel(indexing, "embedding", models);
  const llm = boundModel(generation, "llm", models);

  return {
    parser: "형식별 자동 선택 · 현재 구성에 고정되지 않음",
    chunker: profileValue(indexing, "chunker", "프로파일에 명시되지 않음"),
    embedding: modelIdentity(embedding),
    sparseRetriever: hasConfig(retrieval, "bm25") ? "BM25" : "사용 안 함",
    denseRetriever: hasConfig(retrieval, "dense")
      ? `Bi-encoder · ${modelIdentity(embedding)}`
      : "사용 안 함",
    fusion: rrfIdentity(retrieval),
    reranker: "사용 안 함 (선택)",
    llm: generation ? modelIdentity(llm) : "사용 안 함 (추출식)",
  };
}

export function isV1CompatibleRetrieval(profile: Profile): boolean {
  if (profile.kind !== "retrieval") return false;
  if (profile.bindings.some((binding) => binding.role === "reranker")) return false;
  if (Object.keys(profile.config).some((key) => key.startsWith("reranker") && key !== "reranker")) {
    return false;
  }
  const setting = profile.config.reranker;
  if (setting === null || setting === undefined) return true;
  if (typeof setting !== "object" || Array.isArray(setting)) return false;
  return Object.keys(setting).length === 1 && setting.enabled === false;
}

export function hasResolvableEmbedding(
  profile: Profile,
  models: ModelDefinition[],
): boolean {
  return profile.kind === "indexing" && boundModel(profile, "embedding", models) !== undefined;
}

export function hasResolvableGeneration(
  profile: Profile,
  models: ModelDefinition[],
): boolean {
  return profile.kind === "generation" && boundModel(profile, "llm", models) !== undefined;
}

export function generationOptionLabel(
  profile: Profile,
  models: ModelDefinition[],
): string {
  return `${profileIdentity(profile)} · ${modelIdentity(boundModel(profile, "llm", models))}`;
}

export function modelIdentity(model: ModelDefinition | undefined): string {
  return model ? `${model.name} v${model.version}` : "연결된 모델 정보 없음";
}

export function profileIdentity(profile: Profile | undefined): string {
  return profile ? `${profile.name} v${profile.version}` : "프로파일 정보 없음";
}

export function indexingOptionLabel(
  profile: Profile,
  models: ModelDefinition[],
): string {
  const embedding = boundModel(profile, "embedding", models);
  return [
    `임베딩: ${modelIdentity(embedding)}`,
    `청킹: ${chunkerOptionIdentity(profile)}`,
    `프로파일 v${profile.version}`,
  ].join(" · ");
}

function boundModel(
  profile: Profile | undefined,
  role: "embedding" | "reranker" | "llm",
  models: ModelDefinition[],
): ModelDefinition | undefined {
  const modelId = profile?.bindings.find((binding) => binding.role === role)?.model_id;
  return models.find((model) => model.id === modelId && model.kind === role);
}

function hasConfig(profile: Profile | undefined, key: string): boolean {
  return Boolean(profile && key in profile.config && profile.config[key] !== null);
}

function profileValue(profile: Profile | undefined, key: string, fallback: string): string {
  if (!profile || !(key in profile.config) || profile.config[key] === null) return fallback;
  return formatValue(profile.config[key]);
}

function chunkerOptionIdentity(profile: Profile): string {
  const chunker = profile.config.chunker;
  if (typeof chunker === "string" || typeof chunker === "number") return String(chunker);
  if (!chunker || typeof chunker !== "object" || Array.isArray(chunker)) {
    return "설정 정보 없음";
  }

  const name = typeof chunker.name === "string" ? chunker.name : "방식 미지정";
  const version = typeof chunker.version === "number" ? ` v${chunker.version}` : "";
  const target = typeof chunker.target_tokens === "number"
    ? String(chunker.target_tokens)
    : "미지정";
  const overlap = typeof chunker.overlap_tokens === "number"
    ? String(chunker.overlap_tokens)
    : "미지정";
  return `${name}${version} / 목표 ${target} / 중첩 ${overlap}`;
}

function rrfIdentity(profile: Profile | undefined): string {
  if (!hasConfig(profile, "rrf")) return "사용 안 함";
  const rrf = profile?.config.rrf;
  if (typeof rrf === "object" && rrf !== null && !Array.isArray(rrf)) {
    const k = rrf.k;
    if (typeof k === "number") return `RRF (k=${k})`;
  }
  return "RRF";
}

function formatValue(value: Profile["config"][string]): string {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) return value.map(String).join(", ");
  if (value && typeof value === "object") {
    const name = typeof value.name === "string" ? value.name : null;
    const version = typeof value.version === "number" ? `v${value.version}` : null;
    const target = typeof value.target_tokens === "number" ? `target ${value.target_tokens}` : null;
    const overlap = typeof value.overlap_tokens === "number" ? `overlap ${value.overlap_tokens}` : null;
    const summary = [name, version, target, overlap].filter(Boolean).join(" · ");
    if (summary) return summary;
  }
  return JSON.stringify(value);
}
