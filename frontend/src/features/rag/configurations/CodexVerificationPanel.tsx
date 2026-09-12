import { useId, useState } from "react";
import { ApiError } from "../../../shared/api/client";
import { codexError, loadCodexStatus, verifyCodexConfiguration, type CodexVerification } from "../models/api";
import styles from "./CodexVerificationPanel.module.css";

export function CodexVerificationPanel({ versionId, disclosure, disclosureVersion, requestedModel }: {
  versionId: string; disclosure: string; disclosureVersion: string; requestedModel?: string | null;
}) {
  const consentId = useId();
  const actionHelpId = useId();
  const [consented, setConsented] = useState(false);
  const [operation, setOperation] = useState<"execute" | "query" | null>(null);
  const [retesting, setRetesting] = useState(false);
  const [previousResult, setPreviousResult] = useState(false);
  const [status, setStatus] = useState<CodexVerification | null>(null); const [error, setError] = useState("");
  const busy = operation !== null;
  const showConsent = !status?.ready || retesting;
  async function check(execute: boolean) {
    if (busy || (execute && !consented)) return;
    setOperation(execute ? "execute" : "query"); setError("");
    if (execute) { setConsented(false); setPreviousResult(true); }
    try {
      const result = execute ? await verifyCodexConfiguration(versionId, { consented: true, disclosure_version: disclosureVersion }) : await loadCodexStatus(versionId);
      setStatus(result); setPreviousResult(false);
      if (execute || !consented) setRetesting(false);
    } catch (error) {
      setPreviousResult(true);
      const outcomeUnknown = execute && (!(error instanceof ApiError) || error.code === "request_failed");
      setError(`${codexError(error)}${outcomeUnknown ? " 실행 결과를 확인할 수 없습니다. 서버에서 검사가 완료되었을 수 있으므로 ‘저장된 검사 상태 조회’로 확인하세요. 자동으로 다시 실행하지 않습니다." : ""}`);
    } finally { setOperation(null); }
  }
  return <section className={styles.panel} aria-label="Codex 구성 연결 검사"><h4>이 구성 버전의 Codex 연결 검사</h4>
    <div className={styles.disclosure}>
      <p>{disclosure}</p>
      <p>서버 합성 질문·이력을 전송하고 근거 없는 답변 보류를 확인합니다. 계정 사용량이 발생하며 문서 답변 품질이나 평가 통과를 대신하지 않습니다.</p>
    </div>
    <div className={styles.models}>
      <p>요청 모델: {status?.requested_provider_model_id ?? requestedModel ?? "확인 필요"}</p>
      <p>{previousResult && status ? "이전 검사 실제 모델" : "실제 모델"}: {status?.observed_provider_model_id ?? "미확인"}</p>
    </div>
    {status ? <div className={styles.result} role={busy ? undefined : "status"}>
      <p>{previousResult ? `이전 검사 결과: ${status.ready ? "통과" : `검사 필요 (${status.safe_error_code ?? "미검증"})`} · 현재 실행 결과는 아직 확인되지 않았습니다.` : status.ready ? "연결 검사 통과 · 전체 준비 상태는 구성 목록을 새로 불러와 확인하세요." : `연결 검사 필요: ${status.safe_error_code ?? "미검증"}`}</p>
      <p>검사 시각: {status.checked_at ? <time dateTime={status.checked_at}>{status.checked_at}</time> : "기록 없음"}</p>
    </div> : null}
    {showConsent ? <><label className={styles.consent} htmlFor={consentId}>
      <input id={consentId} type="checkbox" checked={consented} disabled={busy} onChange={(event) => setConsented(event.target.checked)} />
      <span>고지와 이 구성 버전의 합성 입력 외부 전송·계정 사용량을 확인하고 연결 검사에 동의합니다.</span>
    </label>
    <p id={actionHelpId} className={styles.help}>
      {busy ? "요청 처리 중에는 동의와 검사 버튼을 사용할 수 없습니다." : consented ? "동의했습니다. 아래 버튼을 누르면 합성 입력으로 연결 검사를 실행합니다." : "위 동의 항목을 선택하면 연결 검사 버튼이 활성화됩니다. 저장된 상태는 동의 없이 조회할 수 있습니다."}
    </p></> : <p className={styles.help}>새 검사를 실행하려면 ‘다시 검사’를 선택하고 외부 전송·계정 사용량에 새로 동의하세요.</p>}
    <div className={styles.actions}>
      {showConsent ? <button className={styles.primaryAction} type="button" aria-describedby={actionHelpId} disabled={busy || !consented} onClick={() => void check(true)}>합성 입력으로 연결 검사</button> : <button className={styles.secondaryAction} type="button" disabled={busy} onClick={() => { setRetesting(true); setConsented(false); }}>다시 검사</button>}
      <button className={styles.secondaryAction} type="button" disabled={busy} onClick={() => void check(false)}>저장된 검사 상태 조회</button>
    </div>
    {busy ? <p className={styles.result} role="status">{operation === "execute" ? "합성 입력으로 연결 검사 실행 중…" : "저장된 검사 상태 조회 중…"}</p> : null}
    {error ? <p className={styles.result} role="alert">{error}</p> : null}
    <a className={styles.refreshLink} href="/admin/rag/configurations">구성 목록 새로 불러오기</a>
  </section>;
}
