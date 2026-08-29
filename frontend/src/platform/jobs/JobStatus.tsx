import { useState } from "react";

import { getJob, type JobState, type JobSummary } from "./api";

const statusLabels: Record<JobState, string> = {
  queued: "대기 중",
  running: "실행 중",
  succeeded: "완료",
  failed: "실패",
};

const stageLabels: Record<string, string> = {
  queued: "실행 대기",
  verifying_object: "원본 확인 중",
  stored: "저장 확인 완료",
  failed: "처리 실패",
};

interface JobStatusProps {
  jobId: string;
  initialStatus: JobState;
  loadJob?: (jobId: string) => Promise<JobSummary>;
}

export function JobStatus({ jobId, initialStatus, loadJob = getJob }: JobStatusProps) {
  const [status, setStatus] = useState(initialStatus);
  const [stage, setStage] = useState(initialStatus === "queued" ? "queued" : initialStatus);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  async function refresh() {
    setRefreshing(true);
    try {
      const job = await loadJob(jobId);
      setStatus(job.status);
      setStage(job.stage);
      setErrorCode(job.error_code);
    } catch {
      setErrorCode("status_unavailable");
    } finally {
      setRefreshing(false);
    }
  }

  return (
    <div className="job-status" aria-live="polite">
      <span className={`job-state ${status}`}>{statusLabels[status]}</span>
      <span className="job-stage">{stageLabels[stage] ?? stage}</span>
      {errorCode ? <span className="job-error">오류 코드: {errorCode}</span> : null}
      <button type="button" onClick={refresh} disabled={refreshing}>
        {refreshing ? "확인 중…" : "상태 새로고침"}
      </button>
    </div>
  );
}
