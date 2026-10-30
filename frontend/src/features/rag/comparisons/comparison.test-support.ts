import type { ComparisonDetail, ComparisonRequest, ComparisonSummary } from "./api";

export function comparisonFixture(id = "synthetic-report"): ComparisonDetail {
  const request: ComparisonRequest = {
    sequence: 1, provider: "OpenAI", model: "synthetic-cloud", repetition: 1, condition: "first",
    duration_seconds: 3.780943, first_token_seconds: null, native_timing: null,
    usage: { input_tokens: 2630, output_tokens: 125, cached_input_tokens: 0, cache_write_tokens: 0, reasoning_tokens: 0 },
    estimated_cost_usd: "0.0003255", actual_billed_cost_usd: null, cost_status: "usage_estimate", pricing_basis: "공개 합성 단가 기준",
    answer: "접수일 기준 4영업일 뒤 지급합니다.", citations: [{ claim_index: 0, evidence_refs: ["e1"] }],
    quality: { schema_valid: true, citation_validator_passed: true, baseline_answer_equal: false, baseline_citations_equal: false,
      semantic_review: "passed", review_summary: "이 질문의 일반 지급 규칙을 설명했습니다.",
      criteria: [{ key: "general_rule", label: "일반 지급 규칙", status: "met", explanation: "접수일 T+4 규칙을 설명합니다." }] },
  };
  const local: ComparisonRequest = { ...request, sequence: 2, provider: "Local", model: "synthetic-local",
    duration_seconds: 159.722676, native_timing: { load_seconds: 14.056393, input_seconds: 133.631998, output_seconds: 11.310529, total_seconds: 159.480035 },
    usage: { input_tokens: 3549, output_tokens: 99, cached_input_tokens: null, cache_write_tokens: null, reasoning_tokens: null },
    estimated_cost_usd: null, actual_billed_cost_usd: null, cost_status: "not_applicable", pricing_basis: null,
    answer: "특정 날짜 예시만 설명한 답변입니다.", quality: { ...request.quality, baseline_answer_equal: true, baseline_citations_equal: true,
      semantic_review: "failed", review_summary: "기존 일반 규칙 누락이 유지됐습니다.", criteria: [{ key: "general_rule", label: "일반 지급 규칙", status: "not_met", explanation: "일반 규칙이 빠졌습니다." }] } };
  return { id, record_kind: "imported_comparison", created_at: "2026-10-29T03:00:00Z", content_sha256: "a".repeat(64), report: {
    schema_version: 1, source_key: `synthetic-${id}`, title: "공개 합성 모델 비교", question: `언제 지급되나요? ${id}`,
    completed_at: "2026-10-29T02:38:39Z", unique_question_count: 1, measurement_scope: "complete_nonstream_generation_response",
    source_result_sha256: "b".repeat(64), source_ledger_sha256: "c".repeat(64), source_input_sha256: "d".repeat(64),
    controls: ["동일 공개 질문과 근거"],
    evidence: [{ ref: "e1", evidence_id: "synthetic-evidence", document_id: "synthetic-document", asset_version_id: "synthetic-version",
      projection_id: "synthetic-projection", index_build_id: "synthetic-build", retrieval_chunk_id: "synthetic-chunk", element_id: "synthetic-element",
      title: "합성 문서", text: "접수일 T+4 영업일", ordinal: 0, page: 2, char_start: 0, char_end: 12,
      bbox: [10, 20, 120, 30], source_kind: "pdf_page" }],
    requests: [request, local,
      { ...request, sequence: 3, repetition: 2, condition: "repeat", duration_seconds: 3.347129, answer: "반복에서도 일반 규칙을 설명합니다.", usage: { ...request.usage, output_tokens: 157 }, estimated_cost_usd: "0.0003415" },
      { ...local, sequence: 4, repetition: 2, condition: "repeat", duration_seconds: 11.122739,
        native_timing: { load_seconds: 0.039163, input_seconds: 0.074523, output_seconds: 10.963106, total_seconds: 11.098752 } }],
    estimated_total_usd: "0.000667", actual_billed_total_usd: null, billing_status: "not_reconciled",
    analysis: [{ title: "입력 처리 차이", body: "반복의 속도 향상을 새로운 질문의 성능으로 일반화하지 않습니다." }],
    limitations: ["고유 질문 한 건으로 전체 모델 정확도를 확정하지 않습니다."],
  } };
}

export function comparisonSummary(): ComparisonSummary {
  const { id, created_at, report } = comparisonFixture();
  return { id, record_kind: "imported_comparison", created_at, source_key: report.source_key, title: report.title, question: report.question,
    completed_at: report.completed_at, unique_question_count: 1, request_count: 4, models: ["synthetic-cloud", "synthetic-local"],
    estimated_total_usd: report.estimated_total_usd, billing_status: report.billing_status };
}
