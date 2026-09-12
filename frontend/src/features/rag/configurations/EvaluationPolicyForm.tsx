import { useState, type FormEvent } from "react";
import type { EvaluationPolicyCreate } from "./api";

const fields = [
  ["min_recall_at_k", "최소 Recall@K", 1], ["min_mrr", "최소 MRR", 1], ["min_ndcg", "최소 nDCG", 1],
  ["min_supported_precision", "최소 SUPPORTED 정밀도", 1], ["max_false_grounding_rate", "최대 잘못된 근거 비율", 1],
  ["min_highlight_iou", "최소 하이라이트 IoU", 1], ["max_p50_latency_ms", "최대 P50 지연 (ms)", undefined], ["max_p95_latency_ms", "최대 P95 지연 (ms)", undefined],
] as const;

export function EvaluationPolicyForm({ snapshotId, retrievalK, disabled, onSave, onEdit }: {
  snapshotId: string | null; retrievalK: number; disabled: boolean;
  onSave: (request: EvaluationPolicyCreate) => void; onEdit: () => void;
}) {
  const [values, setValues] = useState<Record<string, string>>({});
  const [error, setError] = useState("");
  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); if (!snapshotId || disabled) return;
    if (fields.some(([key, , max]) => !values[key]?.trim() || !Number.isFinite(Number(values[key])) || Number(values[key]) < 0 || (max !== undefined && Number(values[key]) > max))) {
      setError("모든 기준을 유한한 숫자로 입력하세요. 비율은 0~1, 지연은 0ms 이상입니다."); return;
    }
    setError("");
    onSave({ dataset_snapshot_id: snapshotId, metric_definition_version: 1, retrieval_k: retrievalK,
      min_recall_at_k: Number(values.min_recall_at_k), min_mrr: Number(values.min_mrr), min_ndcg: Number(values.min_ndcg),
      min_supported_precision: Number(values.min_supported_precision), max_false_grounding_rate: Number(values.max_false_grounding_rate), min_highlight_iou: Number(values.min_highlight_iou),
      max_p50_latency_ms: Number(values.max_p50_latency_ms), max_p95_latency_ms: Number(values.max_p95_latency_ms), max_access_leaks: 0, required_reproducibility: 1,
    });
  }
  return <form onSubmit={submit}><h3>4. 통과 기준과 정책 저장</h3>
    <p>비율은 0~1, 지연은 ms입니다. 관찰된 점수를 복사하지 않고 기준을 직접 정하세요. 접근권한 누출 허용 0 · 필수 재현성 1 (고정). Retrieval K {retrievalK}에 묶입니다.</p>
    <fieldset disabled={disabled}><legend>수동 통과 기준</legend>
      {fields.map(([key, label, max]) => <label key={key}>{label}<input type="number" min={0} max={max} step="any" required value={values[key] ?? ""} onChange={(event) => { setValues((current) => ({ ...current, [key]: event.target.value })); setError(""); onEdit(); }} /></label>)}
    </fieldset>
    {!snapshotId ? <p>기준은 지금 작성할 수 있습니다. 최초 실제 실행에서 반환된 자료 스냅샷이 있어야 정책을 저장합니다.</p> : null}
    <button disabled={!snapshotId || disabled}>평가 정책 저장</button>{error ? <p role="alert">{error}</p> : null}
  </form>;
}
