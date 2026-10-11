import Link from "next/link";
import type { GenerativeRun } from "./generative-api";
import { buildSourceHref } from "../search/source-route-query";
import styles from "./GenerativeEvaluation.module.css";
import { CalculationProofReview } from "./CalculationProofReview";

type Attempt = GenerativeRun["attempts"][number];

export function ClaimCitationReview({ claims, sources }: {
  claims: Attempt["claim_citations"];
  sources: Attempt["sources"];
}) {
  return <details className={styles.claimReview}>
    <summary>주장별 인용 근거</summary>
    <p>저장된 주장과 인용 위치를 확인합니다. 내용이 원문에서 뒷받침되는지는 별도로 검토하세요.</p>
    {!claims?.length ? <p>원래 주장 텍스트 경계가 기록되지 않았습니다. 합쳐진 답변에서 경계를 추정하지 않습니다.</p> :
      <ol className={styles.claimList}>{claims.map(claim => {
        const matched = sources.filter(source => claim.evidence_ids.includes(source.evidence_id));
        const missingSource = claim.evidence_ids.some(id => !matched.some(source => source.evidence_id === id));
        const locations = new Map<string, { source: Attempt["sources"][number]; count: number }>();
        for (const source of matched) {
          const key = JSON.stringify([source.asset_version_id, source.projection_id, source.page]);
          const existing = locations.get(key);
          if (existing) existing.count += 1;
          else locations.set(key, { source, count: 1 });
        }
        return <li key={claim.claim_index}>
          <h4>주장 {claim.claim_index + 1}</h4>
          <p className={styles.claimText}>{claim.claim_text ?? "원래 주장 텍스트 경계가 기록되지 않았습니다. 합쳐진 답변에서 경계를 추정하지 않습니다."}</p>
          {matched.length ? <ul>{[...locations].map(([key, { source, count }]) => <li key={key}>
            <Link href={buildSourceHref(source.asset_version_id, source.projection_id, [], source.page)}>{source.title} · {source.page == null ? "페이지 미기록" : `${source.page}쪽`} 인용 원문 · 근거 {count}건</Link>
          </li>)}</ul> : <p>현재 조회 가능한 인용 원문이 없습니다.</p>}
          {matched.length > 0 && missingSource ? <p>일부 인용 원문은 현재 조회할 수 없습니다.</p> : null}
          <CalculationProofReview claimText={claim.claim_text} calculations={claim.calculations} sources={matched} />
        </li>;
      })}</ol>}
  </details>;
}
