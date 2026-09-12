import { fireEvent, render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { EvaluationPolicyForm } from "./EvaluationPolicyForm";

it("requires explicit finite thresholds and binds fixed safety metrics to the returned snapshot", () => {
  const save = vi.fn(); const edit = vi.fn();
  render(<EvaluationPolicyForm snapshotId="returned-snapshot" retrievalK={7} disabled={false} onSave={save} onEdit={edit} />);
  const form = screen.getByRole("heading", { name: "4. 통과 기준과 정책 저장" }).closest("form")!;
  expect(screen.getAllByRole("spinbutton").every((input) => (input as HTMLInputElement).value === "")).toBe(true);
  fireEvent.submit(form);
  expect(screen.getByRole("alert")).toHaveTextContent("유한한 숫자");
  expect(save).not.toHaveBeenCalled();
  for (const label of ["최소 Recall@K", "최소 MRR", "최소 nDCG", "최소 SUPPORTED 정밀도", "최대 잘못된 근거 비율", "최소 하이라이트 IoU"]) fireEvent.change(screen.getByRole("spinbutton", { name: label }), { target: { value: "0.5" } });
  fireEvent.change(screen.getByRole("spinbutton", { name: "최대 P50 지연 (ms)" }), { target: { value: "200" } });
  fireEvent.change(screen.getByRole("spinbutton", { name: "최대 P95 지연 (ms)" }), { target: { value: "400" } });
  expect(save).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole("spinbutton", { name: "최소 MRR" }), { target: { value: "2" } });
  fireEvent.submit(form); expect(save).not.toHaveBeenCalled();
  fireEvent.change(screen.getByRole("spinbutton", { name: "최소 MRR" }), { target: { value: "0.6" } });
  fireEvent.submit(form);
  expect(save).toHaveBeenCalledWith({ dataset_snapshot_id: "returned-snapshot", metric_definition_version: 1, retrieval_k: 7, min_recall_at_k: 0.5, min_mrr: 0.6, min_ndcg: 0.5, min_supported_precision: 0.5, max_false_grounding_rate: 0.5, min_highlight_iou: 0.5, max_p50_latency_ms: 200, max_p95_latency_ms: 400, max_access_leaks: 0, required_reproducibility: 1 });
});
