export type JobState = "queued" | "running" | "succeeded" | "failed";

export interface JobSummary {
  id: string;
  type: "verify_asset";
  status: JobState;
  stage: string;
  attempt: number;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export async function getJob(jobId: string): Promise<JobSummary> {
  const response = await fetch(`/api/v1/jobs/${jobId}`, { credentials: "include" });
  if (!response.ok) throw new Error("작업 상태를 불러오지 못했습니다.");
  return (await response.json()) as JobSummary;
}
