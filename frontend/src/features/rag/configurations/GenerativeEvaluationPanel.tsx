import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import { executionPath } from "../../../shared/routing/routes";
import { buildSourceHref } from "../search/source-route-query";
import { EvaluationAuthoringPanel } from "./EvaluationAuthoringPanel";
import type { SavedConfiguration, Workspace } from "./api";
import { loadConfigurations } from "./api";
import * as api from "./generative-api";
import styles from "../executions/ExecutionMonitoring.module.css";

const judgmentLabel = { passed: "통과", failed: "실패", unreviewed: "미검증" };
const coverage = (value: number | null | undefined) => value == null ? "대상 없음" : `${(value * 100).toFixed(1)}%`;
const runLabel: Record<string, string> = { pending: "대기", running: "실행 중", completed: "실행 완료", failed: "실행 실패", interrupted: "중단" };

export function GenerativeEvaluationPanel({ configurations, workspaces, initialRunId, initialCaseId, onConfigurationUpdated }: {
  configurations: SavedConfiguration[]; workspaces: Workspace[]; initialRunId?: string; initialCaseId?: string;
  onConfigurationUpdated?: (configuration: SavedConfiguration) => void;
}) {
  const [runs, setRuns] = useState<api.GenerativeRun[]>([]);
  const [policies, setPolicies] = useState<api.GenerativePolicy[]>([]);
  const [current, setCurrent] = useState<api.GenerativeRun | null>(null);
  const [caseId, setCaseId] = useState(initialCaseId ?? "");
  const [snapshot, setSnapshot] = useState<api.AuthoringSnapshot | null>(null);
  const [rules, setRules] = useState<Record<string, api.GenerativeRule>>({});
  const [versions, setVersions] = useState<string[]>([]);
  const [policyId, setPolicyId] = useState("");
  const [policyName, setPolicyName] = useState("");
  const [thresholds, setThresholds] = useState({ context: "1", correctness: "1", abstention: "1", latency: "120000" });
  const [policyVersion, setPolicyVersion] = useState(1);
  const [repetitions, setRepetitions] = useState(2);
  const [retrievalK, setRetrievalK] = useState(10);
  const [histories, setHistories] = useState<Record<string, string>>({});
  const submission = useRef<{ fingerprint: string; id: string } | null>(null);
  const [classification, setClassification] = useState<"" | "public" | "synthetic">("");
  const [consented, setConsented] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [reviewReasons, setReviewReasons] = useState<Record<string, string>>({});
  const intent = useRef(0);
  const live = useRef(true);
  useEffect(() => {
    live.current = true;
    const controller = new AbortController();
    Promise.all([api.listGenerativeRuns(controller.signal), api.listGenerativePolicies(controller.signal),
      initialRunId ? api.loadGenerativeRun(initialRunId, controller.signal) : Promise.resolve(null),
    ]).then(([items, saved, selected]) => {
      if (!controller.signal.aborted) { setRuns(items); setPolicies(saved); setCurrent(selected); }
    }).catch(() => { if (!controller.signal.aborted) setError("평가 기록을 열 수 없습니다. 로그인과 현재 원문 권한을 확인해 주세요."); });
    return () => { live.current = false; controller.abort(); };
  }, [initialRunId]);
  function linkState(run: string, selectedCase: string) {
    const url = new URL(window.location.href); url.searchParams.set("tab", "comparison");
    if (run) url.searchParams.set("run", run); else url.searchParams.delete("run");
    if (selectedCase) url.searchParams.set("case", selectedCase); else url.searchParams.delete("case");
    window.history.replaceState(null, "", url);
  }
  function receiveRun(run: api.GenerativeRun) {
    setCurrent(run); setRuns(items => [run, ...items.filter(item => item.id !== run.id)]); linkState(run.id, caseId);
  }
  async function perform(action: () => Promise<void>) {
    if (busy) return;
    setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (cause) { if (live.current) setError(cause instanceof ApiError ? cause.message : "요청을 처리하지 못했습니다. 현재 입력은 유지됩니다."); }
    finally { if (live.current) setBusy(false); }
  }
  const available = configurations.filter(item => item.generation_profile_id && !item.is_system);
  const chosen = available.filter(item => versions.includes(item.version_id));
  const codex = chosen.some(item => item.generation_execution_preview?.provider === "development_codex_exec");
  const external = chosen.some(item => item.generation_execution_preview?.external_transfer);
  const disclosure = chosen.find(item => item.generation_execution_preview?.provider === "development_codex_exec")?.generation_execution_preview?.disclosure_version;
  const attempts = current?.attempts.filter(item => !caseId || item.case_id === caseId) ?? [];
  const cases = [...new Map(current?.attempts.map(item => [item.case_id, item.query]) ?? []).entries()];
  return <section className={styles.page} aria-label="생성형 평가">
    <h2>생성형 평가 · generative-v1</h2>
    <p>실제 대화와 같은 문맥 선택·생성·인용 검증을 실행합니다. 인용 유효성과 정답 여부를 별도로 확인합니다.</p>
    {error ? <p role="alert">{error}</p> : null}{message ? <p role="status">{message}</p> : null}
    <details className={styles.card}><summary>새 생성형 평가 준비</summary>
      <EvaluationAuthoringPanel configurations={available} workspaces={workspaces} onRun={() => {}}
        onInvalidate={() => { setSnapshot(null); setRules({}); }} beginOperation={() => ++intent.current} isCurrentOperation={value => value === intent.current}
        onSnapshot={(value, k, count) => {
          setRetrievalK(k); setRepetitions(count); setHistories({});
          setSnapshot(value); setRules(Object.fromEntries(value.cases.map(item => [item.id, {
            version: 1, expected_answer_status: item.expected_answer_status === "insufficient_evidence" ? "insufficient_evidence" : "answered",
            required_evidence_groups: item.expected_evidence_ids.map(id => [id]), required_propositions: [], forbidden_propositions: [],
          }])));
        }} />
      {snapshot ? <section><h3>답변 내용 판정 범위</h3><p>아래 문자열 규칙을 비워 두면 답변 내용은 미검증이며 별도 검토가 필요합니다. 규칙 일치는 일반적인 의미 정확도를 보장하지 않습니다.</p>
        {snapshot.cases.map(item => <fieldset key={item.id} disabled={busy}><legend>{item.query}</legend>
          <label>이전 질문 문맥 (선택, 원문 그대로 고정)<textarea value={histories[item.id] ?? ""} maxLength={8000} onChange={event => setHistories(values => ({ ...values, [item.id]: event.target.value }))} /></label>
          <label>반드시 포함할 내용 (한 줄에 하나)<textarea onChange={event => setRules(values => ({ ...values, [item.id]: { ...values[item.id], required_propositions: event.target.value.split("\n").filter(v => v.trim()) } }))} /></label>
          <label>포함하면 안 되는 내용 (한 줄에 하나)<textarea onChange={event => setRules(values => ({ ...values, [item.id]: { ...values[item.id], forbidden_propositions: event.target.value.split("\n").filter(v => v.trim()) } }))} /></label>
        </fieldset>)}
      </section> : null}
      <fieldset disabled={busy}><legend>비교할 저장 구성 버전</legend>{available.map(item => <label key={item.version_id}><input type="checkbox" checked={versions.includes(item.version_id)} onChange={event => setVersions(values => event.target.checked ? [...values, item.version_id] : values.filter(id => id !== item.version_id))} />{item.name} v{item.version}</label>)}</fieldset>
      <details><summary>생성형 승격 기준 저장</summary><fieldset disabled={busy}>
        <label>기준 이름<input value={policyName} onChange={event => setPolicyName(event.target.value)} /></label>
        <label>기준 버전<input type="number" min={1} value={policyVersion} onChange={event => setPolicyVersion(Number(event.target.value))} /></label>
        {([['context', '최소 문맥 근거 충족률'], ['correctness', '최소 정답 비율'], ['abstention', '최소 거절 정확도'], ['latency', '최대 P95 시간 (ms)']] as const).map(([key, label]) => <label key={key}>{label}<input type="number" min={0} max={key === "latency" ? undefined : 1} step="any" value={thresholds[key]} onChange={event => setThresholds(values => ({ ...values, [key]: event.target.value }))} /></label>)}
        <button type="button" disabled={!policyName.trim()} onClick={() => void perform(async () => {
          const policy = await api.createGenerativePolicy({ name: policyName.trim(), definition: { version: policyVersion, min_context_coverage: Number(thresholds.context), min_correctness: Number(thresholds.correctness), min_abstention: Number(thresholds.abstention), max_p95_latency_ms: Number(thresholds.latency), require_valid_citations: true, max_access_leaks: 0 } });
          setPolicies(values => [policy, ...values.filter(value => value.id !== policy.id)]); setPolicyId(policy.id); setMessage("승격 기준을 저장했습니다.");
        })}>승격 기준 저장</button>
      </fieldset></details>
      <fieldset disabled={busy}><legend>명시적 생성 실행</legend>
        <label>생성형 승격 기준<select value={policyId} onChange={event => setPolicyId(event.target.value)}><option value="">저장된 기준 선택</option>{policies.map(item => <option key={item.id} value={item.id}>{item.name} v{item.definition.version}</option>)}</select></label>
        <p>검색 K {retrievalK} · 사례별 {repetitions}회 반복 (위 평가 자료 설정)</p>
        {codex ? <label>질문 자료 분류<select value={classification} onChange={event => setClassification(event.target.value as typeof classification)}><option value="">선택</option><option value="synthetic">합성 자료</option><option value="public">공개 자료</option></select></label> : null}
        {external ? <label><input type="checkbox" checked={consented} onChange={event => setConsented(event.target.checked)} />모든 평가 질문·이전 문맥·승인된 근거의 외부 처리와 반복 실행 사용량을 확인했습니다.</label> : null}
        <button type="button" disabled={!snapshot || !versions.length || !policyId || (external && !consented) || (codex && (!classification || !disclosure))} onClick={() => void perform(async () => {
          if (!snapshot) return;
          const input = { dataset_snapshot_id: snapshot.id, configuration_version_ids: versions, policy_id: policyId, expected_rules: rules, repetition_count: repetitions, retrieval_k: retrievalK,
            case_histories: Object.fromEntries(Object.entries(histories).filter(([, value]) => value.trim()).map(([id, content]) => [id, [{ role: "user" as const, content }]])),
            ...(codex && classification && disclosure ? { input_approval: { classification, consented: true, disclosure_version: disclosure } } : {}) };
          const fingerprint = JSON.stringify(input);
          if (submission.current?.fingerprint !== fingerprint) submission.current = { fingerprint, id: crypto.randomUUID() };
          const run = await api.startGenerativeRun({ ...input, request_id: submission.current.id });
          receiveRun(run); setMessage("생성형 평가를 요청했습니다. 기존 worker가 저장된 작업을 실행합니다.");
        })}>생성형 평가 실행</button>
      </fieldset>
    </details>
    <label>생성형 실행<select value={current?.id ?? ""} disabled={busy} onChange={event => void perform(async () => { if (event.target.value) { setCaseId(""); const run = await api.loadGenerativeRun(event.target.value); receiveRun(run); linkState(run.id, ""); } })}><option value="">실행 선택</option>{runs.map(item => <option key={item.id} value={item.id}>{new Date(item.created_at).toLocaleString("ko-KR")} · {runLabel[item.status] ?? item.status}</option>)}</select></label>
    {current ? <>
      <div className={styles.badges}><span>실행: {runLabel[current.status] ?? current.status}</span><span>사례별 {current.repetition_count}회</span><button disabled={busy} onClick={() => void perform(async () => receiveRun(await api.loadGenerativeRun(current.id)))}>결과 새로고침</button>
        {current.status === "failed" ? <button disabled={busy} onClick={() => void perform(async () => receiveRun(await api.retryGenerativeRun(current.id)))}>실패한 사례 재시도</button> : null}</div>
      <label>평가 사례<select value={caseId} onChange={event => { setCaseId(event.target.value); linkState(current.id, event.target.value); }}><option value="">모든 사례</option>{cases.map(([id, query]) => <option key={id} value={id}>{query}</option>)}</select></label>
      {caseId && !attempts.length ? <p role="alert">연결된 사례를 찾을 수 없습니다.</p> : null}
      {attempts.map(item => <article className={styles.card} key={item.id}>
        <h3>{item.query}</h3><p>{configurations.find(c => c.version_id === item.configuration_version_id)?.name ?? "저장 구성"} · 반복 {item.repetition + 1} · 시도 {item.attempt_number} · {runLabel[item.status] ?? item.status}</p>
        <div className={styles.badges}><span>정답: {judgmentLabel[item.metrics?.correctness ?? "unreviewed"]}</span><span>인용: {item.metrics?.citation_valid == null ? "미검증" : item.metrics.citation_valid ? "유효" : "실패"}</span><span>생성: {item.metrics?.generation_completed ? "완료" : "미완료"}</span></div>
        <p className={styles.answer}>{item.answer ?? "저장된 생성 답변이 없습니다."}</p>{item.error_code ? <p role="alert">{item.error_code}</p> : null}
        <dl><dt>검색 근거 충족률</dt><dd>{coverage(item.metrics?.retrieval_coverage)}</dd><dt>문맥 근거 충족률</dt><dd>{coverage(item.metrics?.context_coverage)} · 필요 그룹 {item.metrics?.required_group_count ?? "미기록"}</dd><dt>거절 정확성</dt><dd>{item.metrics?.abstention_correct == null ? "대상 없음" : item.metrics.abstention_correct ? "통과" : "실패"}</dd><dt>소요 시간</dt><dd>{item.metrics?.duration_ms == null ? "시간 미기록" : `${item.metrics.duration_ms.toFixed(0)} ms`}</dd></dl>
        {item.judgment ? <p>판정 출처: {item.judgment.provenance === "rule" ? `정답 규칙 v${item.judgment.rule_version} (문자열 조건 범위)` : `검토자 ${item.judgment.reviewer_id} · ${item.judgment.reviewed_at}`} · {item.judgment.reason}</p> : null}
        {item.execution_id ? <Link href={executionPath(item.execution_id)}>실행 단계 상세</Link> : <p>연결된 실행 기록이 없습니다.</p>}
        <div className={styles.badges}>{item.sources.map(source => <Link key={source.evidence_id} href={buildSourceHref(source.asset_version_id, source.projection_id, [], source.page)}>{source.title} · {source.page ?? "—"}쪽 인용 원문</Link>)}</div>
        {item.status === "completed" && item.result_digest ? <details><summary>이 답변 검토</summary><label>검토 근거<textarea value={reviewReasons[item.id] ?? ""} onChange={event => setReviewReasons(values => ({ ...values, [item.id]: event.target.value }))} /></label>
          {(["passed", "failed", "unreviewed"] as const).map(status => <button key={status} disabled={busy || !reviewReasons[item.id]?.trim()} onClick={() => void perform(async () => receiveRun(await api.reviewGenerativeAttempt(current.id, item.id, { result_digest: item.result_digest!, status, reason: reviewReasons[item.id] })))}>{judgmentLabel[status]}로 기록</button>)}
        </details> : null}
      </article>)}
      {current.status === "completed" ? <details><summary>DB 검증 후 구성에 생성형 통과 반영</summary><p>저장된 기준과 모든 반복 사례의 증거를 DB에서 재검증합니다. 활성 도메인 연결 변경은 별도 관리 동작입니다.</p>{[...new Set(current.attempts.map(item => item.configuration_version_id))].map(version => <button key={version} disabled={busy} onClick={() => void perform(async () => {
        await api.acceptGenerativeRun(current.id, version); setMessage("정확한 구성 버전에 생성형 평가 통과를 반영했습니다.");
        if (onConfigurationUpdated) for (const config of await loadConfigurations()) onConfigurationUpdated(config);
      })}>{configurations.find(c => c.version_id === version)?.name ?? "구성"} 통과 검증·반영</button>)}</details> : null}
    </> : <p>읽기만으로 평가가 실행되지는 않습니다. 저장된 실행을 선택하세요.</p>}
  </section>;
}
