import type { components } from "../../../shared/api/schema";

type Trace = NonNullable<components["schemas"]["CandidateDiagnosticResponse"]["budget_trace"]>;

export function BudgetTrace({ trace, reason }: { trace?: Trace | null; reason: string }) {
  if (!trace) {
    if (reason === "budget_exceeded" || reason === "conflict_context_budget_exceeded") {
      return <div><small>세부 예산 미기록</small></div>;
    }
    if (reason === "below_threshold") return <div><small>예산 검사 전 제외</small></div>;
    return null;
  }
  if (trace.violated.length === 0) {
    return reason === "conflict_context_budget_exceeded"
      ? <div><small>선택 검사 후 상충 근거 보존을 위해 전달 취소</small></div> : null;
  }
  const constraints = {
    groups: { label: "문맥 묶음", incoming: 1, remaining: trace.group_limit - trace.before_groups, limit: trace.group_limit, unit: "개" },
    units: { label: "원문 단위", incoming: trace.incoming_units, remaining: trace.unit_limit - trace.before_units, limit: trace.unit_limit, unit: "개" },
    characters: { label: "문자", incoming: trace.incoming_characters, remaining: trace.character_limit - trace.before_characters, limit: trace.character_limit, unit: "자" },
  };
  return <>{trace.violated.map(kind => {
    const value = constraints[kind];
    return <div key={kind}><small>{value.label} {value.incoming}{value.unit} / 남은 {value.remaining}{value.unit} (전체 한도 {value.limit}{value.unit})</small></div>;
  })}</>;
}
