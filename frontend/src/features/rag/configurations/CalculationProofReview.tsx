import Link from "next/link";
import type { components } from "../../../shared/api/schema";
import { buildSourceHref } from "../search/source-route-query";
import styles from "./GenerativeEvaluation.module.css";

type Calculation = components["schemas"]["VerifiedCalculationView"];
type Source = components["schemas"]["GenerativeSourceView"];

export function CalculationProofReview({ claimText, calculations, sources }: {
  claimText: string | null | undefined;
  calculations: readonly Calculation[] | null | undefined;
  sources: readonly Source[];
}) {
  if (calculations == null) return <p>계산 근거 미기록</p>;
  if (!calculations.length) return <p>이 주장에는 계산이 없습니다.</p>;
  return <details className={styles.calculationReview}>
    <summary>계산 근거</summary>
    <p>원문 피연산자와 산술 검증 기록입니다. 질문의 의미에 맞는 답인지는 별도로 검토하세요.</p>
    <ol>{calculations.map((proof, index) => <li key={`${index}-${proof.result_start}-${proof.result_end}`}>
      <p>{proof.operation === "percentage_point_difference" ? "퍼센트포인트 차이" : "금액 단위 환산"} · 결과 {[...(claimText ?? "")].slice(proof.result_start, proof.result_end).join("")}</p>
      <ol>{proof.operands.map((operand, position) => {
        const source = sources.find(item => item.evidence_id === operand.evidence_id && item.document_id === operand.document_id && item.asset_version_id === operand.asset_version_id && item.projection_id === operand.projection_id);
        return <li key={`${position}-${operand.evidence_id}-${operand.token_start}`}>
          피연산자 {position + 1} · 단위 {operand.unit} · 원문 위치 {operand.char_start}–{operand.char_end}{" · "}
          {source ? <Link href={buildSourceHref(source.asset_version_id, source.projection_id, [], operand.page)}>{source.title} · {operand.page == null ? "페이지 미기록" : `${operand.page}쪽`} 원문</Link> : "현재 원문 접근 불가"}
        </li>;
      })}</ol>
    </li>)}</ol>
  </details>;
}
