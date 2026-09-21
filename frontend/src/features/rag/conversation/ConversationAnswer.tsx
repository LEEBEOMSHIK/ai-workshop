import type { Evidence } from "./api";
import type { CompletedTurn } from "./types";
import type { DocumentSummary } from "../../assets/api";
import { scopeSummary } from "./types";
import { CodexModelIdentity } from "./CodexModelIdentity";
import { SearchDiagnostics } from "./SearchDiagnostics";
import { buildSourceHref } from "../search/source-route-query";

export function ConversationAnswer({ turn, onOpenEvidence, onOpenSelectedVersion }: {
  turn: CompletedTurn;
  onOpenEvidence: (evidence: Evidence) => void;
  onOpenSelectedVersion: (document: DocumentSummary, versionId: string) => void;
}) {
  const evidenceById = new Map(
    [turn.result.answer, ...turn.result.conflicts, ...(turn.result.grounding_evidence ?? [])]
      .filter((item): item is Evidence => item !== null)
      .map((item) => [item.source.evidence_unit_id, item]),
  );
  const generation = turn.result.generation;
  const missingCitation = generation.citations.some((citation) => citation.evidence_ids.some((id) => !evidenceById.has(id)));
  const citations = generation.citations.flatMap((citation) => citation.evidence_ids.flatMap((evidenceId) => {
    const evidence = evidenceById.get(evidenceId);
    return evidence ? [{ claimIndex: citation.claim_index, evidence }] : [];
  }));
  return (
    <article className="conversation-turn" aria-label={`${turn.query}에 대한 답변`}>
      <p className="user-message"><strong>나</strong>{turn.query}</p>
      <section className="assistant-message">
        <h2>AI 답변</h2>
        {generation.execution ? <CodexModelIdentity execution={generation.execution} /> : null}
        {generation.status === "answered" && generation.text && !missingCitation ? <p>{generation.text}</p> : null}
        {missingCitation ? <p role="alert">답변 인용에 연결할 원문 근거가 누락되어 답변을 표시하지 않았습니다.</p> : null}
        {generation.status === "insufficient_evidence" ? (
          <div className="answer-state insufficient" role="status"><strong>답변할 근거가 부족합니다.</strong><p>{insufficientReason(generation.reason_codes)}</p></div>
        ) : null}
        {generation.status === "citation_validation_failed" ? (
          <div className="answer-state insufficient" role="alert"><strong>인용을 검증하지 못해 생성 답변을 표시하지 않았습니다.</strong><p>확인 가능한 원문 근거만 검토해 주세요.</p></div>
        ) : null}
        {generation.status === "not_requested" ? (
          <div className="answer-state insufficient" role="alert"><strong>생성 답변을 실행하지 못했습니다.</strong><p>도메인 연결 상태를 확인한 뒤 다시 시도해 주세요.</p></div>
        ) : null}
        <p className="answer-scope">응답 범위: {scopeSummary(turn.scope)}</p>
        {turn.result.selected_scope ? <ul className="answer-selected-scope" aria-label="실제 사용 문서">
          {turn.result.selected_scope.identities.map((identity) => {
            const document = turn.scope.documents.find((candidate) => candidate.id === identity.document_id);
            return document ? <li key={identity.document_id}>
              <span>실제 사용 문서: {document.name}</span>
              <button type="button" aria-label={`${document.name} 사용 버전 원문 열기`} onClick={() => onOpenSelectedVersion(document, identity.asset_version_id)}>사용 버전 원문 열기</button>
            </li> : <li key={identity.document_id}>
              <span>{[...evidenceById.values()].find(evidence => evidence.source.document_id === identity.document_id)?.source.title ?? "사용 문서"}</span>
              <a href={buildSourceHref(identity.asset_version_id, identity.projection_id)}>사용 버전 원문 열기</a>
            </li>;
          })}
        </ul> : null}
        {generation.status === "answered" && generation.citations.length > 0 ? (
          <ul className="conversation-citations" aria-label="답변 인용">
            {citations.map(({ claimIndex, evidence }, index) => {
              const number = index + 1;
              return <li key={`${claimIndex}-${evidence.source.evidence_unit_id}`}><button type="button" onClick={() => onOpenEvidence(evidence)} aria-label={`인용 ${number}: ${evidence.source.title}`}>[{number}] {evidence.source.title}</button></li>;
            })}
          </ul>
        ) : null}
        {turn.result.answer ? (
          <details className="conversation-evidence"><summary>확인된 근거</summary><blockquote>{turn.result.answer.excerpt}</blockquote><button type="button" onClick={() => onOpenEvidence(turn.result.answer!)}>원문에서 확인</button></details>
        ) : null}
        {turn.result.diagnostics ? <SearchDiagnostics diagnostics={turn.result.diagnostics} query={turn.result.resolved_query} /> : <details className="conversation-evidence"><summary>검색 근거·유사도</summary><p>이 응답에는 진단 기록이 없습니다.</p></details>}
      </section>
    </article>
  );
}

function insufficientReason(codes: string[]): string {
  const messages: Record<string, string> = {
    no_search_results: "선택한 범위에서 검색 결과를 찾지 못했습니다.",
    no_eligible_evidence: "검색 결과에서 생성에 전달할 근거가 선택되지 않았습니다. 검색 근거·유사도에서 임계값과 입력 예산에 따른 선택 사유를 확인해 주세요.",
    evidence_below_threshold: "검색된 자료가 근거 선택 기준을 충족하지 못했습니다.",
    evidence_budget_exceeded: "생성 입력 예산 안에 필요한 근거를 담지 못했습니다.",
    evidence_content_insufficient: "전달된 근거의 내용만으로 질문에 답할 수 없습니다.",
  };
  return codes.map(code => messages[code]).filter(Boolean).join(" ") || "기록된 상세 사유가 없습니다. 검색 근거·유사도에서 검색 결과와 선택 사유를 확인해 주세요.";
}
