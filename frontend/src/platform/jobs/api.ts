import { apiRequest } from "../../shared/api/client";
import type { components } from "../../shared/api/schema";

export type JobState = components["schemas"]["JobStatus"];
export type JobSummary = components["schemas"]["JobResponse"];

export async function getJob(jobId: string): Promise<JobSummary> {
  return apiRequest<JobSummary>(`/api/v1/jobs/${jobId}`);
}
