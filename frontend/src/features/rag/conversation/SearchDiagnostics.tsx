import type { DomainSearchResult } from "./api";
import { buildSourceHref } from "../search/source-route-query";

const reasons: Record<string, string> = {
  selected: "선택", context_member: "문맥으로 포함", below_threshold: "임계값 미달",
  budget_exceeded: "입력 예산 초과", not_transmitted: "생성에 전달하지 않음",
  legacy_selected: "기존 정책으로 선택", conflict_context_budget_exceeded: "충돌 근거 예산 부족",
};
const stages: Record<string, string> = {
  retrieval: "검색", selection: "근거 선택", contextualization: "질문 재작성",
  generation: "답변 생성", total: "서버 전체 처리",
};

function score(value: number | null | undefined) {
  return value == null ? "미계산" : <span title={String(value)}>{value.toFixed(4)}</span>;
}

export function SearchDiagnostics({ diagnostics, query }: {
  diagnostics: NonNullable<DomainSearchResult["diagnostics"]>;
  query: string;
}) {
  const contexts = new Map(diagnostics.candidates.filter((item) => item.evidence_unit_id === null)
    .map((item) => [item.source.chunk_id, item.semantic_score]));
  return <details className="conversation-evidence">
    <summary>검색 근거·유사도 · {new Set(diagnostics.candidates.map(item => item.source.asset_version_id)).size}개 문서</summary>
    <p>실제 검색 질문: <span>{query}</span></p>
    {diagnostics.warning ? <p role="status">일부 진단 점수를 계산하지 못했습니다. 미계산 값은 선택 점수로 사용하지 않았습니다.</p> : null}
    <p>반환된 검색 후보만 표시합니다. 점수는 정답 확률이 아닙니다. BM25·벡터 원점수·RRF·코사인 유사도는 서로 다른 척도입니다.</p>
    <p>의미 임계값: {score(diagnostics.min_semantic_score)} · 키워드 포함률 임계값: {score(diagnostics.min_keyword_coverage)}</p>
    <div style={{ overflowX: "auto" }}>
      <table aria-label="검색 후보와 근거 점수">
        <thead><tr><th>원문 / 단위</th><th>BM25 원점수 / 순위</th><th>벡터 원점수 / 순위</th><th>RRF / 순위</th><th>문장 코사인 유사도</th><th>문맥 코사인 유사도</th><th>키워드 포함률</th><th>자격 / 전달</th><th>사유</th></tr></thead>
        <tbody>{diagnostics.candidates.map((item) => <tr key={`${item.source.chunk_id}:${item.evidence_unit_id ?? "context"}`}>
          <td><a href={buildSourceHref(item.source.asset_version_id, item.source.projection_id)} target="_blank" rel="noopener noreferrer">{item.source.title}</a><br />{item.source.section_path.join(" / ")}<br />{item.evidence_unit_id ? "문장" : "문맥"} <small>{item.evidence_unit_id ?? item.source.chunk_id}</small></td>
          <td>{score(item.sparse_score)} / {item.sparse_rank ?? "미계산"}</td>
          <td>{score(item.dense_score)} / {item.dense_rank ?? "미계산"}</td>
          <td>{score(item.source.fused_score)} / {item.fused_rank}</td>
          <td>{score(item.evidence_unit_id ? item.semantic_score : null)}</td>
          <td>{score(contexts.get(item.source.chunk_id))}</td>
          <td>{score(item.keyword_coverage)}</td>
          <td>{item.eligible ? "통과" : "미달"} / {item.selected ? "전달" : "제외"}</td>
          <td>{reasons[item.reason] ?? item.reason}</td>
        </tr>)}</tbody>
      </table>
    </div>
    {diagnostics.candidates.length === 0 ? <p>표시할 유효한 검색 후보가 없습니다.</p> : null}
    <dl>{Object.entries(diagnostics.stages_ms).map(([stage, value]) => <div key={stage}>
      <dt>{stages[stage] ?? stage}</dt><dd>{value === null ? "미실행" : `${value.toFixed(1)} ms`}</dd>
    </div>)}</dl>
    <p>단계 시간은 중첩되거나 병렬로 실행될 수 있어 합계가 전체 시간과 같지 않을 수 있습니다.</p>
  </details>;
}
