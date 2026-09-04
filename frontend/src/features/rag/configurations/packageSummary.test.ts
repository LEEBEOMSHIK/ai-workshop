import { describe, expect, it } from "vitest";

import type { ModelDefinition, Profile } from "./api";
import { isV1CompatibleRetrieval, summarizeRagPackage } from "./packageSummary";

describe("summarizeRagPackage", () => {
  it("describes a hybrid package without inventing unsupported parser, reranker, or LLM identities", () => {
    const models: ModelDefinition[] = [
      { id: "embedding-1", kind: "embedding", name: "multilingual-e5-base", version: 1, config: {} },
    ];
    const indexing = profile("indexing", {
      parser: "값이 있어도 현재 계약에서는 고정값이 아님",
      chunker: { name: "structure-aware", version: 2, target_tokens: 380, overlap_tokens: 60 },
    }, [{ role: "embedding", model_id: "embedding-1" }]);
    const retrieval = profile("retrieval", {
      bm25: {}, dense: { top_k: 30 }, rrf: { k: 60 }, reranker: { enabled: false },
    });

    expect(summarizeRagPackage({ indexing, retrieval, models })).toEqual({
      parser: "형식별 자동 선택 · 현재 구성에 고정되지 않음",
      chunker: "structure-aware · v2 · target 380 · overlap 60",
      embedding: "multilingual-e5-base v1",
      sparseRetriever: "BM25",
      denseRetriever: "Bi-encoder · multilingual-e5-base v1",
      fusion: "RRF (k=60)",
      reranker: "사용 안 함 (선택)",
      llm: "사용 안 함 (추출식)",
    });
  });

  it("accepts only the exact disabled-reranker metadata supported by extractive V1", () => {
    expect(isV1CompatibleRetrieval(profile("retrieval", { bm25: {}, reranker: { enabled: false } }))).toBe(true);
    expect(isV1CompatibleRetrieval(profile("retrieval", { bm25: {}, reranker: { enabled: true } }))).toBe(false);
    expect(isV1CompatibleRetrieval(profile("retrieval", { bm25: {}, reranker: { enabled: false, optional: true } }))).toBe(false);
    expect(isV1CompatibleRetrieval(profile("retrieval", { bm25: {} }, [
      { role: "reranker", model_id: "reranker-1" },
    ]))).toBe(false);
  });
});

function profile(
  kind: Profile["kind"],
  config: Profile["config"],
  bindings: Profile["bindings"] = [],
): Profile {
  return {
    id: `${kind}-1`,
    kind,
    name: `${kind}-profile`,
    version: 1,
    config,
    bindings,
    deployment_version_id: null,
    legacy: false,
    readiness: { ready: false, reason_codes: [] },
    evaluation_state: "draft",
    is_default: false,
  };
}
