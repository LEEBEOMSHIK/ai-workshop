import { apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";

export type ComparisonDetail = components["schemas"]["ComparisonDetail"];
export type ComparisonSummary = components["schemas"]["ComparisonSummary"];
export type ComparisonImport = components["schemas"]["ComparisonImport"];
export type ComparisonRequest = components["schemas"]["ComparisonRequest"];
export type ComparisonEvidence = components["schemas"]["ComparisonEvidence"];
type ComparisonList = components["schemas"]["ComparisonList"];

const endpoint = "/api/v1/admin/rag/comparisons";

export function listComparisonReports(signal?: AbortSignal) {
  return apiRequest<ComparisonList>(endpoint, { signal, cache: "no-store" });
}

export function getComparisonReport(id: string, signal?: AbortSignal) {
  return apiRequest<ComparisonDetail>(`${endpoint}/${encodeURIComponent(id)}`, { signal, cache: "no-store" });
}

export function importComparisonReport(payload: unknown, signal?: AbortSignal) {
  return apiRequest<ComparisonDetail>(endpoint, { method: "POST", json: payload, signal, cache: "no-store", headers: { "X-Comparison-Request": "1" } });
}
