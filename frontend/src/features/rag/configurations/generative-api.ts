import { apiRequest } from "../../../shared/api/client";
import type { components } from "../../../shared/api/schema";

export type GenerativeRun = components["schemas"]["GenerativeRunView"];
export type GenerativeRunCreate = components["schemas"]["GenerativeRunCreate"];
export type GenerativePolicy = components["schemas"]["GenerativePolicyView"];
export type GenerativePolicyCreate = components["schemas"]["GenerativePolicyCreate"];
export type GenerativeRule = components["schemas"]["ExpectedAnswerRule"];
export type AuthoringSnapshot = components["schemas"]["AuthoringSnapshotResponse"];
const base = "/api/v1/rag/generative-evaluations";
export const listGenerativeRuns = (signal?: AbortSignal) => apiRequest<GenerativeRun[]>(base, { signal });
export const loadGenerativeRun = (id: string, signal?: AbortSignal) => apiRequest<GenerativeRun>(`${base}/${encodeURIComponent(id)}`, { signal });
export const listGenerativePolicies = (signal?: AbortSignal) => apiRequest<GenerativePolicy[]>(`${base}/policies`, { signal });
export const createGenerativePolicy = (json: GenerativePolicyCreate) => apiRequest<GenerativePolicy>(`${base}/policies`, { method: "POST", json });
export const startGenerativeRun = (json: GenerativeRunCreate) => apiRequest<GenerativeRun>(base, { method: "POST", json, headers: { "x-codex-request": "1" } });
export const retryGenerativeRun = (id: string) => apiRequest<GenerativeRun>(`${base}/${encodeURIComponent(id)}/retry`, { method: "POST", json: {}, headers: { "x-codex-request": "1" } });
export const reviewGenerativeAttempt = (run: string, attempt: string, json: components["schemas"]["GenerativeReviewRequest"]) => apiRequest<GenerativeRun>(`${base}/${encodeURIComponent(run)}/attempts/${encodeURIComponent(attempt)}/judgments`, { method: "POST", json });
export const acceptGenerativeRun = (run: string, version: string) => apiRequest<components["schemas"]["GenerativeAcceptanceView"]>(`${base}/${encodeURIComponent(run)}/accept/${encodeURIComponent(version)}`, { method: "POST" });

export const loadAuthoringSnapshot = (id: string) => apiRequest<AuthoringSnapshot>(`/api/v1/rag/evaluation-authoring/snapshots/${encodeURIComponent(id)}`);
