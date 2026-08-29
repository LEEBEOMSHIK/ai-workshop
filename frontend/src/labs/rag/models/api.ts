export type ModelKind = "embedding" | "reranker" | "llm";
export type ProfileKind = "indexing" | "retrieval" | "generation";
export type EvaluationState = "draft" | "pending" | "passed" | "failed";
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export interface ModelDefinitionSummary {
  id: string;
  kind: ModelKind;
  name: string;
  version: number;
  config: Record<string, JsonValue>;
}

export interface ProfileBindingSummary {
  role: ModelKind;
  model_id: string;
}

export interface ProfileSummary {
  id: string;
  kind: ProfileKind;
  name: string;
  version: number;
  config: Record<string, JsonValue>;
  bindings: ProfileBindingSummary[];
  evaluation_state: EvaluationState;
  is_default: boolean;
}

export interface ModelLabData {
  models: ModelDefinitionSummary[];
  profiles: ProfileSummary[];
}

async function expectJson<T>(response: Response, message: string): Promise<T> {
  if (!response.ok) throw new Error(message);
  return (await response.json()) as T;
}

export async function loadModelLab(): Promise<ModelLabData> {
  const [modelsResponse, ...profileResponses] = await Promise.all([
    fetch("/api/v1/rag/models", { credentials: "include" }),
    ...(["indexing", "retrieval", "generation"] as ProfileKind[]).map((kind) =>
      fetch(`/api/v1/rag/profiles/${kind}`, { credentials: "include" }),
    ),
  ]);
  const models = await expectJson<ModelDefinitionSummary[]>(
    modelsResponse,
    "모델 목록을 불러오지 못했습니다.",
  );
  const profileGroups = await Promise.all(
    profileResponses.map((response) =>
      expectJson<ProfileSummary[]>(response, "프로파일 목록을 불러오지 못했습니다."),
    ),
  );
  return { models, profiles: profileGroups.flat() };
}

export async function registerModelVersion(input: {
  kind: ModelKind;
  name: string;
  version: number;
  config: Record<string, JsonValue>;
}): Promise<ModelDefinitionSummary> {
  const response = await fetch("/api/v1/rag/models", {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  return expectJson(response, "모델 버전을 등록하지 못했습니다.");
}

export async function registerYamlProfile(
  kind: ProfileKind,
  content: string,
): Promise<ProfileSummary> {
  const response = await fetch(`/api/v1/rag/profiles/${kind}/yaml`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ content }),
  });
  return expectJson(response, "YAML 프로파일을 등록하지 못했습니다.");
}
