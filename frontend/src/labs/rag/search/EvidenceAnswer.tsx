import { useId } from "react";
import { Link } from "react-router-dom";

import type { EvidenceAnswerData, SearchResult } from "./api";

interface EvidenceAnswerProps {
  result: SearchResult;
  workspaceNames: ReadonlyMap<string, string>;
}

export function EvidenceAnswer({ result, workspaceNames }: EvidenceAnswerProps) {
  const answer = result.status === "supported" ? result.answer : null;
  const supported = answer !== null;

  return (
    <div className="answer-stack">
      <section className={`answer-state ${supported ? "supported" : "insufficient"}`}>
        <div role="status">
          <h2>{supported ? "근거로 답변할 수 있습니다" : "직접 답할 근거가 부족합니다"}</h2>
          <p>
            {supported
              ? "아래 원문 발췌와 위치를 확인해 주세요."
              : "관련 문서는 참고할 수 있지만 답변 근거로 확정하지 않았습니다."}
          </p>
          {!supported && result.warnings.length > 0 ? (
            <p className="provenance-warning">
              원문 위치 정보가 완전하지 않은 후보는 답변 근거에서 제외했습니다.
            </p>
          ) : null}
        </div>
        <p className="configuration-version">구성 버전 {result.configuration_version.version}</p>
      </section>

      {supported ? (
        <section className="evidence-section" aria-labelledby="confirmed-evidence-title">
          <h2 id="confirmed-evidence-title">확인된 근거</h2>
          <EvidenceCard answer={answer} workspaceNames={workspaceNames} />
        </section>
      ) : null}

      {result.conflict_state === "separate_sources" && result.conflicts.length > 0 ? (
        <section className="conflict-section" aria-labelledby="conflict-sources-title">
          <h2 id="conflict-sources-title">충돌하는 근거</h2>
          <p>서로 다른 원문 발췌를 분리해 표시합니다. 하나의 답변으로 합성하지 않았습니다.</p>
          <div className="source-card-list">
            {result.conflicts.map((answer) => (
              <EvidenceCard
                key={`${answer.source.asset_version_id}-${answer.source.evidence_unit_id}`}
                answer={answer}
                workspaceNames={workspaceNames}
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
  workspaceNames,
}: {
  answer: EvidenceAnswerData;
  workspaceNames: ReadonlyMap<string, string>;
}) {
  const warningId = useId();
  const warnings = Array.from(
    new Set([...answer.warnings, ...answer.highlights.flatMap((highlight) => highlight.warnings)]),
  );
  const workspaceName = workspaceNames.get(answer.source.workspace_id);
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
          {workspaceName ? <span className="workspace-badge">{workspaceName}</span> : null}
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
        to={`/rag/sources/${answer.source.asset_version_id}?projectionId=${encodeURIComponent(answer.source.projection_id)}`}
        state={{
          highlights: answer.highlights,
          page: answer.source.location.page,
        }}
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
