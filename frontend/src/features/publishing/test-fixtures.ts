import type { StudyAdminView, StudySnapshot } from "./types";

export function studySnapshot(
  content: Partial<StudySnapshot["content"]> = {},
): StudySnapshot {
  return {
    schema_version: 1,
    revision: 3,
    content: {
      slug: "hybrid-search",
      title: "하이브리드 검색 실험",
      summary: "검색 기준선 비교",
      topic_keys: ["retrieval", "rag"],
      body: "BM25와 dense 검색을 비교했습니다.",
      verification: "고정 질의로 재현했습니다.",
      limitations: "소규모 데이터셋만 확인했습니다.",
      persona: null,
      ...content,
    },
  };
}

export function adminStudy(overrides: Partial<StudyAdminView> = {}): StudyAdminView {
  return {
    snapshot: studySnapshot(),
    digest: "a".repeat(64),
    sequence: 1,
    approved_digest: null,
    desired_action: null,
    applied_sequence: 0,
    applied_action: null,
    applied_revision: null,
    delivery_pending: false,
    last_request_id: null,
    delivery_error_code: null,
    pending_command: null,
    ...overrides,
  };
}
