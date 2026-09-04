import type { ModelDefinition, Profile, SavedConfiguration } from "./api";
import { profileIdentity, summarizeRagPackage } from "./packageSummary";

const evaluationLabels: Record<SavedConfiguration["evaluation_state"], string> = {
  draft: "초안",
  pending: "평가 대기",
  passed: "평가 통과",
  failed: "평가 실패",
};

export function SavedConfigurationList({
  configurations,
  models,
  profiles,
}: {
  configurations: SavedConfiguration[];
  models: ModelDefinition[];
  profiles: Profile[];
}) {
  const ordered = [...configurations].sort((left, right) => {
    if (left.is_system !== right.is_system) return left.is_system ? -1 : 1;
    return left.name.localeCompare(right.name, "ko");
  });

  return (
    <section className="saved-configuration-list" aria-label="저장된 RAG 구성">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">IMMUTABLE VERSIONS</p>
          <h2>저장된 RAG 구성</h2>
        </div>
        <p>시스템 기준선과 실제 저장에 성공한 버전만 표시합니다.</p>
      </div>
      {ordered.length === 0 ? <p role="status">저장된 구성이 없습니다.</p> : null}
      <div className="saved-configuration-grid">
        {ordered.map((configuration) => {
          const indexing = profiles.find((profile) => profile.id === configuration.indexing_profile_id);
          const retrieval = profiles.find((profile) => profile.id === configuration.retrieval_profile_id);
          const generation = profiles.find(
            (profile) => profile.id === configuration.generation_profile_id,
          );
          const embedding = indexing?.bindings
            .filter((binding) => binding.role === "embedding")
            .map((binding) => models.find((model) => model.id === binding.model_id))
            .find((model) => model !== undefined);
          const summary = summarizeRagPackage({ indexing, retrieval, generation, models });
          return (
            <article className="saved-configuration-card" key={configuration.version_id}>
              <div className="configuration-card-heading">
                <h3>{configuration.name}</h3>
                <div className="configuration-badges">
                  {configuration.is_system ? <span>시스템</span> : <span>사용자 저장</span>}
                  {configuration.is_default ? <span>운영 기본값</span> : null}
                  {configuration.experimental ? <span>실험</span> : null}
                </div>
              </div>
              <p className="configuration-package-label">RAG 패키지 구성</p>
              <dl className="identity-list package-component-list">
                <div><dt>불변 버전</dt><dd>v{configuration.version}</dd></div>
                <div><dt>평가 상태</dt><dd>{evaluationLabels[configuration.evaluation_state]}</dd></div>
                <div><dt>Indexing</dt><dd>{profileIdentity(indexing)}</dd></div>
                <div><dt>Retrieval</dt><dd>{profileIdentity(retrieval)}</dd></div>
                <div><dt>Generation</dt><dd>{profileIdentity(generation)}</dd></div>
                <div><dt>Parser</dt><dd>{summary.parser}</dd></div>
                <div><dt>Chunker</dt><dd>{summary.chunker}</dd></div>
                <div><dt>Embedding</dt><dd>{summary.embedding}</dd></div>
                <div><dt>Sparse Retriever</dt><dd>{summary.sparseRetriever}</dd></div>
                <div><dt>Dense Retriever</dt><dd>{summary.denseRetriever}</dd></div>
                <div><dt>Fusion</dt><dd>{summary.fusion}</dd></div>
                <div><dt>Reranker</dt><dd>{summary.reranker}</dd></div>
                <div><dt>Answer Policy</dt><dd>{configuration.answer_policy.mode} v{configuration.answer_policy.version}</dd></div>
                <div><dt>LLM</dt><dd>{summary.llm}</dd></div>
                <div><dt>검색 준비</dt><dd>{configuration.search_ready ? "완료" : "준비 필요"}</dd></div>
                <div><dt>답변 준비</dt><dd>{configuration.answer_ready ? "완료" : "준비 필요"}</dd></div>
                <div><dt>서비스 상태</dt><dd>{configuration.service_ready ? "사용 가능" : "사용 불가"}</dd></div>
              </dl>
              {!configuration.service_ready ? (
                <p className="configuration-readiness" role="status">
                  {readinessMessage(configuration)}
                </p>
              ) : null}
              <details className="technical-identifiers">
                <summary>기술 식별자 보기</summary>
                <dl className="identity-list">
                  <div><dt>구성 ID</dt><dd>{configuration.id}</dd></div>
                  <div><dt>구성 버전 ID</dt><dd>{configuration.version_id}</dd></div>
                  <div><dt>색인 프로파일 ID</dt><dd>{configuration.indexing_profile_id}</dd></div>
                  <div><dt>임베딩 모델 ID</dt><dd>{embedding?.id ?? "연결 정보 없음"}</dd></div>
                  <div><dt>검색 프로파일 ID</dt><dd>{configuration.retrieval_profile_id}</dd></div>
                  <div><dt>생성 프로파일 ID</dt><dd>{configuration.generation_profile_id ?? "사용 안 함"}</dd></div>
                  <div><dt>답변 정책 ID</dt><dd>{configuration.answer_policy.id}</dd></div>
                  <div><dt>지식 공간 ID</dt><dd>{configuration.workspace_ids.join(", ") || "없음"}</dd></div>
                </dl>
              </details>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function readinessMessage(configuration: SavedConfiguration): string {
  const reasons = [...configuration.search_reasons, ...configuration.answer_reasons];
  if (reasons.length === 0) return "구성 요소의 실행 준비 상태를 확인해 주세요.";
  return `준비 필요: ${reasons.map(readinessReasonLabel).join(", ")}`;
}

function readinessReasonLabel(reason: string): string {
  const labels: Record<string, string> = {
    generation_not_configured: "생성 프로파일 미구성",
    generation_profile_not_found: "생성 프로파일을 찾을 수 없음",
    generation_model_not_found: "LLM 모델을 찾을 수 없음",
    generation_runtime_not_configured: "로컬 LLM 실행 주소 미설정",
    generation_runtime_unavailable: "로컬 LLM 실행기 응답 없음",
    generation_runtime_model_mismatch: "실행 중인 LLM 버전 불일치",
    deployment_not_allowed_in_environment: "현재 환경에서 실행 배포를 사용할 수 없음",
    workspace_external_transfer_denied: "지식 공간 정책에서 외부 전송을 허용하지 않음",
    provider_not_allowed: "회사 정책에서 외부 공급자를 허용하지 않음",
    deployment_not_ready: "실행 배포 준비 확인 필요",
    provider_authentication_failed: "공급자 인증 확인 필요",
    provider_rate_limited: "공급자 요청 한도 초과",
    provider_timeout: "공급자 응답 시간 초과",
    provider_invalid_response: "공급자 응답 확인 필요",
  };
  return labels[reason] ?? "답변 실행 준비 상태 확인 필요";
}
