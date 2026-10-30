import type { ComparisonRequest } from "./api";
import { comparisonModelKey as modelKey, comparisonModelOrder, formatComparisonDuration as duration, formatComparisonMoney as money, formatComparisonTokens as tokens } from "./comparison-format";
import styles from "./Comparisons.module.css";

type Metric = { label: string; value: (request: ComparisonRequest) => string; prominent?: boolean };
const timingMetrics: readonly Metric[] = [
  { label: "완료 응답", value: request => duration(request.duration_seconds), prominent: true },
  { label: "첫 토큰", value: request => duration(request.first_token_seconds) },
  { label: "로드", value: request => duration(request.native_timing?.load_seconds) },
  { label: "입력 처리", value: request => duration(request.native_timing?.input_seconds) },
  { label: "출력 생성", value: request => duration(request.native_timing?.output_seconds) },
  { label: "서버 전체", value: request => duration(request.native_timing?.total_seconds) },
];
const usageMetrics: readonly Metric[] = [
  { label: "입력 토큰", value: request => tokens(request.usage.input_tokens) },
  { label: "출력 토큰", value: request => tokens(request.usage.output_tokens) },
  { label: "캐시 읽기 토큰", value: request => tokens(request.usage.cached_input_tokens) },
  { label: "캐시 쓰기 토큰", value: request => tokens(request.usage.cache_write_tokens) },
  { label: "추론 토큰", value: request => tokens(request.usage.reasoning_tokens) },
  { label: "예상 API 비용", value: request => request.cost_status === "not_applicable" ? "API 청구 해당 없음" : money(request.estimated_cost_usd) },
  { label: "실제 청구액", value: request => request.cost_status === "not_applicable" ? "해당 없음" : money(request.actual_billed_cost_usd) },
];

export function ComparisonMetricGroups({ requests, kind }: { requests: ComparisonRequest[]; kind: "timing" | "usage" }) {
  const modelOrder = comparisonModelOrder(requests);
  const metrics = kind === "timing" ? timingMetrics : usageMetrics;
  const subject = kind === "timing" ? "처리 시간" : "사용량·비용";

  return <div className={styles.metricGroups}>
    {modelOrder.map(identity => {
      // Only recorded requests become columns; absent model runs are never filled with zeroes.
      const group = requests.filter(request => modelKey(request) === identity)
        .sort((a, b) => a.repetition - b.repetition);
      const { provider, model } = group[0];
      const label = `${provider} · ${model}`;
      return <section key={identity} className={styles.metricGroup} aria-label={`${label} ${subject}`}>
        <header className={styles.metricGroupHeading}>
          <h3>{provider}</h3>
          <p className={styles.muted}>{model}</p>
        </header>
        <div className={styles.metricScroll} tabIndex={0} role="region" aria-label={`${label} ${subject} 표`}>
          <table className={styles.metricTable} style={group.length > 2 ? { minWidth: `${(group.length + 1) * 9}rem` } : undefined}>
            <caption>{label} — {subject}</caption>
            <colgroup><col className={styles.metricLabelColumn} />{group.map(request => <col key={request.sequence} />)}</colgroup>
            <thead><tr><th scope="col">측정 항목</th>{group.map(request => <th scope="col" key={request.sequence}>
              <span className={styles.metricProvider}>{request.condition === "first" ? "첫 요청" : "동일 입력 반복"}</span>
              <small>{request.repetition}회차 · 요청 {request.sequence}</small>
            </th>)}</tr></thead>
            <tbody>{metrics.map(metric => <tr key={metric.label} className={metric.prominent ? styles.primaryMetric : undefined}>
              <th scope="row">{metric.label}</th>
              {group.map(request => <td key={request.sequence}>{metric.value(request)}</td>)}
            </tr>)}</tbody>
          </table>
        </div>
        {group.length > 2 ? <p className={styles.metricScrollHint}>회차가 많은 표는 표 안을 좌우로 이동해 확인하세요.</p> : null}
      </section>;
    })}
  </div>;
}
