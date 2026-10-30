import Link from "next/link";
import { useState } from "react";
import { ChoiceGroup } from "../../../shared/ui/ChoiceGroup";
import { buildSourceHref } from "../search/source-route-query";
import type { ComparisonDetail, ComparisonEvidence, ComparisonRequest } from "./api";
import { comparisonModelKey, comparisonModelOrder, formatComparisonDuration as duration, formatComparisonMoney as money } from "./comparison-format";
import { ComparisonMetricGroups } from "./ComparisonMetricGroups";
import styles from "./Comparisons.module.css";

const semanticLabels = { passed: "충족", failed: "미충족", partial: "부분 충족", unreviewed: "미검토" };
const criterionLabels = { met: "충족", not_met: "미충족", not_applicable: "해당 없음", unreviewed: "미검토" };
export const billingLabels = { not_reconciled: "청구 미확인", reconciled: "청구 대조 완료", not_applicable: "API 청구 해당 없음" };
const condition = (request: ComparisonRequest) => request.condition === "first" ? "첫 요청" : `동일 입력 반복 · ${request.repetition}회차`;

function evidenceHref(evidence: ComparisonEvidence) {
  const bbox = evidence.bbox?.length === 4 ? evidence.bbox as [number, number, number, number] : null;
  return buildSourceHref(evidence.asset_version_id, evidence.projection_id, [{
    evidence_unit_id: evidence.evidence_id, text: evidence.text, char_start: evidence.char_start, char_end: evidence.char_end,
    page: evidence.page, bbox, kind: "context", score: null, warnings: [],
  }], evidence.page);
}

function RecordedCitations({ request, evidence }: { request: ComparisonRequest; evidence: ComparisonEvidence[] }) {
  const byRef = new Map(evidence.map(item => [item.ref, item]));
  return <section className={styles.citations} aria-label={`${request.model} 인용 근거`}>
    <h4>답변에 인용된 원문</h4>
    {request.citations.map(citation => <details key={citation.claim_index}>
      <summary>주장 {citation.claim_index + 1} · 인용 근거 {citation.evidence_refs.length}개</summary>
      <ul>{citation.evidence_refs.map(ref => {
        const source = byRef.get(ref);
        return <li key={ref}>{source ? <>
          <p className={styles.evidenceText}>{source.text}</p>
          <Link className={styles.navigationLink} href={evidenceHref(source)}>{ref} · {source.title} · {source.page == null ? "페이지 미기록" : `${source.page}쪽`} 원문</Link>
        </> : <p>인용 원문 연결을 확인할 수 없습니다.</p>}</li>;
      })}</ul>
    </details>)}
  </section>;
}

function RequestCard({ request, evidence }: { request: ComparisonRequest; evidence: ComparisonEvidence[] }) {
  const quality = request.quality;
  return <article className={styles.requestCard} aria-label={`${request.model} · ${condition(request)}`}>
    <header><p className={styles.eyebrow}>요청 {request.sequence} · {request.provider} · {condition(request)}</p>
      <h3>{request.model}</h3><p className={styles.requestTime}>완료 응답 <strong>{duration(request.duration_seconds)}</strong></p>
    </header>
    <section><h4>실제 저장 답변</h4><p className={styles.answer}>{request.answer}</p></section>
    <section aria-label="기록된 품질 검토">
      <p className={styles.judgment} data-status={quality.semantic_review}>해당 질문 의미 검토: {semanticLabels[quality.semantic_review]}</p>
      <p>{quality.review_summary}</p>
      <div className={styles.badges}><span>형식 검사: {quality.schema_valid ? "통과" : "실패"}</span><span>인용 검사: {quality.citation_validator_passed ? "통과" : "실패"}</span></div>
      <p className={styles.muted}>{quality.baseline_answer_equal == null ? "기존 답변 일치 미검토" : quality.baseline_answer_equal ? "기존 답변과 동일" : "기존 답변과 다름"}</p>
      <p className={styles.muted}>{quality.baseline_citations_equal == null ? "기존 인용 일치 미검토" : quality.baseline_citations_equal ? "기존 인용과 동일" : "기존 인용과 다름"}</p>
      <ul className={styles.criteria}>{quality.criteria.map(item => <li key={item.key} data-status={item.status}>
        <div><strong>{item.label}</strong><span>{criterionLabels[item.status]}</span></div><p>{item.explanation}</p>
      </li>)}</ul>
    </section>
    <RecordedCitations request={request} evidence={evidence} />
  </article>;
}

export function ComparisonReportView({ detail }: { detail: ComparisonDetail }) {
  const report = detail.report;
  const repetitions = [...new Set(report.requests.map(request => request.repetition))].sort((a, b) => a - b);
  const [selected, setSelected] = useState(String(repetitions[0]));
  const active = repetitions.some(value => String(value) === selected) ? selected : String(repetitions[0]);
  const modelOrder = comparisonModelOrder(report.requests);
  const visibleRequests = report.requests.filter(request => String(request.repetition) === active)
    .sort((a, b) => modelOrder.indexOf(comparisonModelKey(a)) - modelOrder.indexOf(comparisonModelKey(b)));
  return <>
    <header className={styles.heading}>
      <p className={styles.eyebrow}>저장된 모델 비교 · 가져온 완료 기록</p>
      <h1>{report.title}</h1><p className={styles.question}>{report.question}</p>
      <p className={styles.muted}>고유 질문 {report.unique_question_count}개 · 완료 요청 {report.requests.length}회 · 근거 {report.evidence.length}개</p>
      <p className={styles.muted}>실제 완료 <time dateTime={report.completed_at}>{new Date(report.completed_at).toLocaleString("ko-KR")}</time> · 사이트 저장 <time dateTime={detail.created_at}>{new Date(detail.created_at).toLocaleString("ko-KR")}</time></p>
    </header>
    <div className={styles.notice}><p>완료된 비교 실행과 검토 내용을 조회합니다. 이 화면을 열거나 새로고침해도 모델을 호출하지 않습니다.</p>
      <p>형식·인용 검사, 이전 답변과의 일치, 해당 질문의 의미 검토는 서로 다른 판단입니다. 전체 모델의 정확도나 운영 기본값 승격을 뜻하지 않습니다.</p>
    </div>
    <section className={styles.panel} aria-labelledby="comparison-timing-title">
      <h2 id="comparison-timing-title">속도와 단계별 처리 시간</h2>
      <p className={styles.muted}>요청 시작부터 답변 전체 수신까지의 시간입니다. 검색·저장·화면 표시를 포함한 전체 RAG 시간과 구분합니다. 첫 요청은 두 모델의 서버 상태를 동일하게 초기화했다는 뜻이 아닙니다.</p>
      <ComparisonMetricGroups requests={report.requests} kind="timing" />
      <p className={styles.muted}>미측정은 0초가 아닙니다. 서버 내부 단계의 합과 완료 응답 시간은 측정 경계가 달라 일치하지 않을 수 있습니다. 동일 입력 반복을 새 질문의 처리 속도로 일반화하지 않습니다.</p>
    </section>
    <section className={styles.answerSection} aria-labelledby="comparison-answer-title">
      <div className={styles.sectionHeading}><div><h2 id="comparison-answer-title">실제 답변·인용·품질 검토</h2><p className={styles.muted}>같은 회차의 저장 답변을 비교합니다. 원문 링크는 현재 접근 권한을 확인합니다.</p></div>
        <ChoiceGroup legend="비교할 회차" variant="segmented" value={active} onChange={setSelected}
          options={repetitions.map(value => ({ value: String(value), label: value === 1 ? "첫 요청 · 1회차" : `동일 입력 반복 · ${value}회차` }))} />
      </div>
      <div className={styles.requests}>{visibleRequests.map(request => <RequestCard key={request.sequence} request={request} evidence={report.evidence} />)}</div>
    </section>
    <section className={styles.panel} aria-labelledby="comparison-cost-title">
      <h2 id="comparison-cost-title">사용량과 비용</h2>
      <dl className={styles.costSummary}><div><dt>사용량 기반 예상 API 비용 합계</dt><dd>{money(report.estimated_total_usd)}</dd></div>
        <div><dt>실제 청구 확인액</dt><dd>{report.billing_status === "not_applicable" ? "해당 없음" : money(report.actual_billed_total_usd)}</dd></div>
        <div><dt>청구 확인 상태</dt><dd>{billingLabels[report.billing_status]}</dd></div>
      </dl>
      <ComparisonMetricGroups requests={report.requests} kind="usage" />
      <p className={styles.muted}>예상 비용과 실제 청구·크레딧 차감은 별개입니다. 로컬 모델의 API 청구가 없다는 뜻이 전력·장치 비용도 0이라는 뜻은 아닙니다. 토크나이저가 다른 모델의 토큰 수는 직접적인 작업량 비교가 아닙니다.</p>
      {report.requests.some(request => request.pricing_basis) ? <details><summary>요청별 비용 계산 근거</summary><ul>{report.requests.filter(request => request.pricing_basis).map(request => <li key={request.sequence}>요청 {request.sequence} · {request.pricing_basis}</li>)}</ul></details> : null}
    </section>
    <section className={styles.panel} aria-labelledby="comparison-analysis-title"><h2 id="comparison-analysis-title">상세 분석</h2>
      <div className={styles.analysis}>{report.analysis.map((section, index) => <section key={index}><h3>{section.title}</h3><p>{section.body}</p></section>)}</div>
    </section>
    <section className={styles.panel} aria-labelledby="comparison-limits-title"><h2 id="comparison-limits-title">비교 조건과 검증 한계</h2>
      <h3>유지한 비교 조건</h3><ul>{report.controls.map((text, index) => <li key={index}>{text}</li>)}</ul>
      <h3>판단할 수 없는 범위</h3><ul>{report.limitations.map((text, index) => <li key={index}>{text}</li>)}</ul>
      <details><summary>기록 출처와 보존 식별자</summary><p>가져온 원본의 식별자입니다. 사이트가 모델을 다시 실행해 결과를 인증한 것은 아닙니다.</p>
        <dl className={styles.provenance}><dt>수입 키</dt><dd>{report.source_key}</dd><dt>결과 SHA256</dt><dd>{report.source_result_sha256}</dd><dt>호출 이력 SHA256</dt><dd>{report.source_ledger_sha256}</dd><dt>입력 SHA256</dt><dd>{report.source_input_sha256}</dd><dt>저장 본문 SHA256</dt><dd>{detail.content_sha256}</dd></dl>
      </details>
    </section>
  </>;
}
