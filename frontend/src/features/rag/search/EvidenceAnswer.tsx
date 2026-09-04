import { useId } from "react";
import Link from "next/link";

import type { EvidenceAnswerData, SearchResult, SearchSubmissionContext } from "./api";
import { ConfigurationProvenance, SourceScopeProvenance } from "./Provenance";
import { buildSourceHref } from "./source-route-query";

interface EvidenceAnswerProps {
  result: SearchResult;
  context: SearchSubmissionContext;
}

export function EvidenceAnswer({ result, context }: EvidenceAnswerProps) {
  const answer = result.status === "supported" ? result.answer : null;
  const supported = answer !== null;
  const globalWarningId = useId();
  const hasGlobalWarning = result.warnings.length > 0;
  const evidenceTitles = new Map(
    [result.answer, ...result.conflicts]
      .filter((item): item is EvidenceAnswerData => item !== null)
      .map((item) => [item.source.evidence_unit_id, item.source.title]),
  );

  return (
    <div className="answer-stack">
      {result.generation?.status === "answered" && result.generation.text ? (
        <section className="generated-answer" aria-labelledby="generated-answer-title">
          <h2 id="generated-answer-title">AI 답변</h2>
          <p>{result.generation.text}</p>
          <ul className="generated-citations" aria-label="답변 인용">
            {result.generation.citations.map((citation) => (
              <li key={`${citation.claim_index}-${citation.evidence_ids.join("-")}`}>
                주장 {citation.claim_index + 1} · {citation.evidence_ids
                  .map((evidenceId) => evidenceTitles.get(evidenceId) ?? "확인된 근거")
                  .join(", ")}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {result.generation?.status === "citation_validation_failed" ? (
        <section className="answer-state insufficient" aria-label="AI 답변 검증 실패">
          <h2>AI 답변을 표시하지 않았습니다</h2>
          <p>생성된 답변의 인용이 현재 검색 근거와 일치하지 않아 원문 근거만 제공합니다.</p>
        </section>
      ) : null}
      <section className={`answer-state ${supported ? "supported" : "insufficient"}`}>
        <div role="status" aria-describedby={hasGlobalWarning ? globalWarningId : undefined}>
          <h2>{supported ? "근거로 답변할 수 있습니다" : "직접 답할 근거가 부족합니다"}</h2>
          <p>
            {supported
              ? "아래 원문 발췌와 위치를 확인해 주세요."
              : "관련 문서는 참고할 수 있지만 답변 근거로 확정하지 않았습니다."}
          </p>
          {hasGlobalWarning ? (
            <p className="provenance-warning" id={globalWarningId}>
              {supported
                ? "검색 결과에 원문 위치 정보가 완전하지 않은 항목이 있습니다."
                : "원문 위치 정보가 완전하지 않은 후보는 답변 근거에서 제외했습니다."}
            </p>
          ) : null}
        </div>
        <ConfigurationProvenance result={result} context={context} />
      </section>

      {supported ? (
        <section className="evidence-section" aria-labelledby="confirmed-evidence-title">
          <h2 id="confirmed-evidence-title">확인된 근거</h2>
          <EvidenceCard answer={answer} context={context} />
        </section>
      ) : null}

      {result.conflict_state === "separate_sources" && result.conflicts.length > 0 ? (
        <section className="conflict-section" aria-labelledby="conflict-sources-title">
          <h2 id="conflict-sources-title">충돌하는 근거</h2>
          <p>서로 다른 원문 발췌를 분리해 표시합니다. 하나의 답변으로 합성하지 않았습니다.</p>
          <ConfigurationProvenance result={result} context={context} />
          <div className="source-card-list">
            {result.conflicts.map((answer) => (
              <EvidenceCard
                key={`${answer.source.asset_version_id}-${answer.source.evidence_unit_id}`}
                answer={answer}
                context={context}
              />
            ))}
          </div>
        </section>
      ) : null}
    </div>
  );
}

function EvidenceCard({
  answer,
  context,
}: {
  answer: EvidenceAnswerData;
  context: SearchSubmissionContext;
}) {
  const warningId = useId();
  const warnings = Array.from(
    new Set([...answer.warnings, ...answer.highlights.flatMap((highlight) => highlight.warnings)]),
  );
  const hasKeyword = answer.highlights.some((highlight) => highlight.kind === "keyword");
  const hasSemantic = answer.highlights.some((highlight) => highlight.kind === "semantic");
  const location = sourceLocation(answer);

  return (
    <article
      className="evidence-card"
      aria-describedby={warnings.length > 0 ? warningId : undefined}
    >
      <div className="evidence-card-header">
        <div>
          <SourceScopeProvenance
            workspaceId={answer.source.workspace_id}
            folderId={answer.source.folder_id}
            context={context}
          />
          <h3>{answer.source.title}</h3>
        </div>
        <span className="immutable-version">버전 {answer.source.asset_version_number}</span>
      </div>
      {location ? <p className="source-location">{location}</p> : null}
      <blockquote>{answer.excerpt}</blockquote>
      <div className="match-badges" aria-label="근거 일치 유형">
        {hasKeyword ? <span className="match-badge keyword">정확·키워드 일치</span> : null}
        {hasSemantic ? <span className="match-badge semantic">의미 일치</span> : null}
      </div>
      {warnings.length > 0 ? (
        <p className="provenance-warning" id={warningId}>
          원문 위치 정보가 완전하지 않습니다.
        </p>
      ) : null}
      <Link
        className="source-link"
        href={buildSourceHref(
          answer.source.asset_version_id,
          answer.source.projection_id,
          answer.highlights,
          answer.source.location.page,
        )}
      >
        원문에서 확인
      </Link>
    </article>
  );
}

function sourceLocation(answer: EvidenceAnswerData): string {
  const parts: string[] = [];
  if (answer.source.location.page !== null) {
    parts.push(`${answer.source.location.page}페이지`);
  }
  if (answer.source.section_path.length > 0) {
    parts.push(answer.source.section_path.join(" › "));
  }
  return parts.join(" · ");
}
