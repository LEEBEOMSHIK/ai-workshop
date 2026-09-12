import { apiRequest } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type EvaluationRun = components["schemas"]["EvaluationRunResponse"];
export type ExperimentFields = components["schemas"]["ExperimentFields"];
export type ExperimentMetric = components["schemas"]["ExperimentMetric"];
export type ExperimentStatus = components["schemas"]["ExperimentStatus"];
export type LearningDraft = components["schemas"]["LearningDraft"];
export type LearningList = components["schemas"]["LearningListResponse"];
export type LearningRecord = components["schemas"]["LearningRecordResponse"];
export type LearningSummary = components["schemas"]["LearningSummaryResponse"];
export type LearningTopic = components["schemas"]["LearningTopicResponse"];
export type RecordKind = components["schemas"]["RecordKind"];
export type ReferenceKey = components["schemas"]["ReferenceKey"];
export type ReferenceView = components["schemas"]["ReferenceViewResponse"];
export type TroubleshootingFields = components["schemas"]["TroubleshootingFields"];

export interface LearningListFilters {
  topicKey?: string;
  kind?: RecordKind;
  archived?: boolean;
  cursor?: string;
  limit?: number;
}

export function listTopics(signal?: AbortSignal): Promise<LearningTopic[]> {
  return apiRequest<LearningTopic[]>("/api/v1/learning/topics", { signal });
}

export function listRecords(
  filters: LearningListFilters = {},
  signal?: AbortSignal,
): Promise<LearningList> {
  const query = new URLSearchParams();
  if (filters.topicKey) query.set("topic_key", filters.topicKey);
  if (filters.kind) query.set("kind", filters.kind);
  if (filters.archived !== undefined) query.set("archived", String(filters.archived));
  if (filters.cursor) query.set("cursor", filters.cursor);
  if (filters.limit !== undefined) query.set("limit", String(filters.limit));
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  return apiRequest<LearningList>(`/api/v1/learning/records${suffix}`, { signal });
}

export function getRecord(recordId: string, signal?: AbortSignal): Promise<LearningRecord> {
  return apiRequest<LearningRecord>(`/api/v1/learning/records/${encodeURIComponent(recordId)}`, { signal });
}

export function getRevision(
  recordId: string,
  revision: number,
  signal?: AbortSignal,
): Promise<LearningRecord> {
  return apiRequest<LearningRecord>(
    `/api/v1/learning/records/${encodeURIComponent(recordId)}/revisions/${revision}`,
    { signal },
  );
}

export function createRecord(draft: LearningDraft): Promise<LearningRecord> {
  return apiRequest<LearningRecord>("/api/v1/learning/records", { method: "POST", json: draft });
}

export function updateRecord(
  recordId: string,
  expectedRevision: number,
  draft: LearningDraft,
): Promise<LearningRecord> {
  return apiRequest<LearningRecord>(`/api/v1/learning/records/${encodeURIComponent(recordId)}`, {
    method: "PUT",
    json: { expected_revision: expectedRevision, draft },
  });
}

export function archiveRecord(recordId: string, expectedRevision: number): Promise<LearningRecord> {
  return revisionMutation(recordId, "archive", expectedRevision);
}

export function restoreRecord(recordId: string, expectedRevision: number): Promise<LearningRecord> {
  return revisionMutation(recordId, "restore", expectedRevision);
}

function revisionMutation(
  recordId: string,
  action: "archive" | "restore",
  expectedRevision: number,
): Promise<LearningRecord> {
  return apiRequest<LearningRecord>(
    `/api/v1/learning/records/${encodeURIComponent(recordId)}/${action}`,
    { method: "POST", json: { expected_revision: expectedRevision } },
  );
}

export function listEvaluationOptions(signal?: AbortSignal): Promise<EvaluationRun[]> {
  return apiRequest<EvaluationRun[]>("/api/v1/rag/evaluation-runs?limit=20", { signal });
}
