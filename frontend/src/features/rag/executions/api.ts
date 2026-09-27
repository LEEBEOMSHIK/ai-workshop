import { apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";

export type ExecutionSearchRequest = Partial<components["schemas"]["ExecutionSearchRequest"]>;
export type ExecutionSearchResponse = components["schemas"]["ExecutionSearchResponse"];
export type ExecutionDetail = components["schemas"]["ExecutionDetailResponse"];
export type Stage = components["schemas"]["StageObservation"];

export function searchExecutions(request: ExecutionSearchRequest, signal?: AbortSignal) {
  return apiRequest<ExecutionSearchResponse>("/api/v1/admin/rag/executions/search", {
    method: "POST", json: request, signal, cache: "no-store",
  });
}

export function getExecutionDetail(id: string, kind: "execution" | "legacy", signal?: AbortSignal) {
  return apiRequest<ExecutionDetail>(`/api/v1/admin/rag/executions/${kind === "legacy" ? "legacy/" : ""}${encodeURIComponent(id)}`, {
    signal, cache: "no-store",
  });
}
