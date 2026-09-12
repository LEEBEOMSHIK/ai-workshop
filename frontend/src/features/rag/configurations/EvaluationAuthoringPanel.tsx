import { useEffect, useRef, useState } from "react";
import { EvaluationSourceSelector } from "./EvaluationSourceSelector";
import { EvaluationCaseEditor } from "./EvaluationCaseEditor";
import { EvaluationPolicyForm } from "./EvaluationPolicyForm";
import { createEvaluationPolicy, startAuthoredEvaluation, startEvaluationRun, type AuthoringCase, type AuthoringPreview, type EvaluationPolicy, type EvaluationPolicyCreate, type EvaluationRun, type SavedConfiguration, type Workspace } from "./api";
import styles from "./EvaluationAuthoring.module.css";

export function EvaluationAuthoringPanel({ configurations, workspaces, onRun, onInvalidate, beginOperation, isCurrentOperation }: {
  configurations: SavedConfiguration[]; workspaces: Workspace[];
  onRun: (run: EvaluationRun) => void; onInvalidate: () => void;
  beginOperation: () => number; isCurrentOperation: (intent: number) => boolean;
}) {
  const [preview, setPreview] = useState<AuthoringPreview | null>(null);
  const [cases, setCases] = useState<AuthoringCase[]>([]);
  const [name, setName] = useState("");
  const [draftId, setDraftId] = useState("");
  const [retention, setRetention] = useState(false);
  const [retrievalK, setRetrievalK] = useState(10);
  const [repetitions, setRepetitions] = useState(2);
  const [snapshotId, setSnapshotId] = useState<string | null>(null);
  const [policy, setPolicy] = useState<EvaluationPolicy | null>(null);
  const [busy, setBusy] = useState(false);
  const [sourceLoading, setSourceLoading] = useState(false);
  const sourcePending = useRef(false);
  const working = busy || sourceLoading;
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const request = useRef<AbortController | null>(null);
  useEffect(() => () => request.current?.abort(), []);
  function freshCase(): AuthoringCase { return { id: crypto.randomUUID(), query: "", expected_answer_status: "supported", expected_evidence_ids: [], expected_highlight: null }; }
  function invalidateDataset() {
    setDraftId(crypto.randomUUID()); setSnapshotId(null); setPolicy(null); setError(""); setMessage(""); onInvalidate();
  }
  function receivePreview(value: AuthoringPreview | null) {
    if (value && preview?.scope_sha256 === value.scope_sha256) { setPreview(value); return; }
    invalidateDataset(); setPreview(value); setRetention(false); setCases(value ? [freshCase()] : []);
  }
  async function execute(operation: "initial" | "policy-run" | "policy", policyRequest?: EvaluationPolicyCreate) {
    if (request.current || sourcePending.current || !preview) return;
    if (operation === "initial" && (!name.trim() || Array.from(name.trim()).length > 180 || !retention || !cases.length || cases.some((item) => !item.query.trim() || (item.expected_answer_status === "supported" && (!item.expected_evidence_ids.length || !item.expected_highlight))))) {
      setError("평가 이름, 질문, 수동 정답 근거·하이라이트와 자료 보관 동의를 확인해 주세요."); return;
    }
    if (!Number.isInteger(retrievalK) || retrievalK < 1 || retrievalK > 50 || !Number.isInteger(repetitions) || repetitions < 2 || repetitions > 5) { setError("K는 1~50, 반복 횟수는 2~5 정수여야 합니다."); return; }
    if (operation === "policy-run" && (!snapshotId || !policy)) return;
    if (operation === "policy" && !policyRequest) return;
    const controller = new AbortController(); request.current = controller; setBusy(true); setError(""); setMessage("");
    const intent = beginOperation();
    const isCurrent = () => !controller.signal.aborted && isCurrentOperation(intent);
    try {
      if (operation === "policy") {
        const saved = await createEvaluationPolicy(policyRequest!, controller.signal);
        if (isCurrent()) { setPolicy(saved); setMessage(`평가 정책 v${saved.version} 저장됨. 다음 실행은 별도로 요청하세요.`); }
      } else {
        const run = operation === "initial"
          ? await startAuthoredEvaluation({ ...preview.scope, scope_sha256: preview.scope_sha256, draft_id: draftId, dataset_name: name.trim(), cases, retrieval_k: retrievalK, repetition_count: repetitions, retention_confirmed: retention }, controller.signal)
          : await startEvaluationRun({ dataset_snapshot_id: snapshotId!, evaluation_policy_version_id: policy!.id, configuration_version_ids: [preview.scope.configuration_version_id], metric_definition_version: 1, retrieval_k: retrievalK, repetition_count: repetitions }, controller.signal);
        if (isCurrent()) {
          setSnapshotId(run.dataset_snapshot_id); onRun(run);
          setMessage(operation === "initial" ? "최초 실행의 자료 스냅샷이 저장되었습니다. 이 실행만으로 평가 통과를 반영할 수 없습니다." : "정책 적용 평가를 요청했습니다. 아래 실제 실행 결과를 확인하세요.");
        }
      }
    } catch {
      if (isCurrent()) setError("요청을 완료하지 못했습니다. 입력과 성공한 단계는 유지했습니다. 범위가 변경되었다면 근거를 다시 조회하고, 같은 이름의 다른 자료 충돌은 새 평가 이름으로 작성하세요.");
    } finally {
      if (!controller.signal.aborted) { request.current = null; setBusy(false); }
    }
  }
  return <section className={styles.authoring}><h2>새 평가 만들기</h2>
    <p>검색 평가 통과, 전체 기본값, 대화 서비스 사용 준비는 서로 다릅니다. 기존 실행은 아래 고급 비교에서 이어갈 수 있습니다.</p>
    <EvaluationSourceSelector configurations={configurations} workspaces={workspaces} disabled={busy} onPreview={receivePreview} beginOperation={beginOperation} isCurrentOperation={isCurrentOperation} onLoading={(loading) => { sourcePending.current = loading; setSourceLoading(loading); }} />
    {preview ? <>
      <h3>2. 전체 근거 확인과 수동 사례 작성</h3>
      <p>선택 문서 {preview.document_count}개 · 전체 근거 {preview.evidence_count}개를 완전히 조회했습니다.</p>
      <ul>{preview.documents.map((document) => <li key={document.asset_version_id}>{document.title} v{document.number}</li>)}</ul>
      <details><summary>조회 범위 기술 식별자</summary><p>{preview.scope_sha256}</p>{preview.documents.map((document) => <p key={document.asset_version_id}>{document.asset_version_id} · {document.sha256}</p>)}</details>
      <fieldset disabled={working}><legend>평가 질문과 정답</legend>
        {cases.map((item, index) => <EvaluationCaseEditor key={item.id} value={item} index={index} evidence={preview.evidence} documents={preview.documents} onChange={(changed) => { invalidateDataset(); setCases((current) => current.map((value) => value.id === changed.id ? changed : value)); }} onRemove={() => { invalidateDataset(); setCases((current) => current.filter((value) => value.id !== item.id)); }} />)}
        <button type="button" disabled={cases.length >= 50} onClick={() => { invalidateDataset(); setCases((current) => [...current, freshCase()]); }}>사례 추가</button>
      </fieldset>
      <h3>3. 자료 보관 확인과 최초 실행</h3>
      <fieldset disabled={working}><legend>초기 평가 실행 입력</legend>
        <label>평가 이름<input value={name} maxLength={180} onChange={(event) => { invalidateDataset(); setName(event.target.value); }} /></label>
        <label>평가 Retrieval K<input type="number" min={1} max={50} value={retrievalK} onChange={(event) => { setPolicy(null); setMessage(""); setError(""); setRetrievalK(Number(event.target.value)); onInvalidate(); }} /></label>
        <label>평가 반복 횟수<input type="number" min={2} max={5} value={repetitions} onChange={(event) => { setMessage(""); setError(""); setRepetitions(Number(event.target.value)); onInvalidate(); }} /></label>
        <label><input type="checkbox" checked={retention} onChange={(event) => setRetention(event.target.checked)} />자료와 질문의 불변 보관을 확인합니다</label>
        <p>원문·질문·수동 정답이 불변 평가 스냅샷에 남습니다. 공개 게시나 학습 등록이 아닙니다. 최초 실행도 실제 반복 검색 평가를 수행합니다.</p>
      </fieldset>
      <button type="button" disabled={working} onClick={() => void execute("initial")}>최초 평가 실행</button>
      <EvaluationPolicyForm snapshotId={snapshotId} retrievalK={retrievalK} disabled={working} onEdit={() => { setPolicy(null); setError(""); setMessage(""); }} onSave={(value) => void execute("policy", value)} />
      <h3>5. 정책을 적용한 실제 평가</h3>
      <button type="button" disabled={working || !snapshotId || !policy} onClick={() => void execute("policy-run")}>정책 적용 평가 실행</button>
      {snapshotId ? <details><summary>저장된 평가 기술 식별자</summary><p>자료 {snapshotId}</p><p>정책 {policy?.id ?? "미저장"}</p></details> : null}
    </> : null}
    {busy ? <p role="status">명시 요청 처리 중…</p> : null}{message ? <p role="status">{message}</p> : null}{error ? <p role="alert">{error}</p> : null}
  </section>;
}
