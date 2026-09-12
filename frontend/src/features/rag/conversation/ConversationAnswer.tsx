import type { Evidence } from "./api";
import type { CompletedTurn } from "./types";
import type { DocumentSummary } from "../../assets/api";
import { scopeSummary } from "./types";
import { CodexModelIdentity } from "./CodexModelIdentity";

export function ConversationAnswer({ turn, onOpenEvidence, onOpenSelectedVersion }: {
  turn: CompletedTurn;
  onOpenEvidence: (evidence: Evidence) => void;
  onOpenSelectedVersion: (document: DocumentSummary, versionId: string) => void;
}) {
  const evidenceById = new Map(
    [turn.result.answer, ...turn.result.conflicts]
      .filter((item): item is Evidence => item !== null)
      .map((item) => [item.source.evidence_unit_id, item]),
  );
  const generation = turn.result.generation;
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
        {generation.status === "answered" && generation.text ? <p>{generation.text}</p> : null}
        {generation.status === "insufficient_evidence" ? (
          <div className="answer-state insufficient" role="status"><strong>답변할 근거가 부족합니다.</strong><p>질문을 구체화하거나 검색 범위를 조정해 주세요.</p></div>
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
            </li> : <li key={identity.document_id}>선택 문서 정보를 표시할 수 없습니다.</li>;
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
      </section>
    </article>
  );
}
