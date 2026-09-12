import { useState, type FormEvent } from "react";
import { codexError, registerDeployment, type CodexRunner, type DeploymentSummary, type ModelDefinitionSummary } from "./api";

export function CodexDeploymentForm({ runners, models, onSaved }: {
  runners: CodexRunner[]; models: ModelDefinitionSummary[]; onSaved: (value: DeploymentSummary) => void;
}) {
  const [runnerRef, setRunnerRef] = useState(runners[0]?.runner_ref ?? "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const runner = runners.find((item) => item.runner_ref === runnerRef);
  const llms = models.filter((item) => item.kind === "llm");
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!runner?.local_preflight_passed || busy) return;
    const form = new FormData(event.currentTarget);
    setBusy(true); setMessage("");
    try {
      const saved = await registerDeployment({
        display_name: String(form.get("name")).trim(), description: "개인 개발용 Codex 실행",
        model_definition_id: String(form.get("model")), provider_model_id: String(form.get("requestedModel")).trim(),
        provider: "development_codex_exec", location: "external", allowed_environments: ["development"],
        runner_ref: runner.runner_ref, endpoint_ref: null, secret_ref: null,
        capabilities: ["structured_output", "contextualization", "token_accounting"],
        external_transfer: true, transmitted_data_categories: ["question", "bounded_history", "evidence", "service_instructions"],
        data_processing_notice_ref: "codex-external-generation-v1",
        timeout_seconds: runner.limits.timeout_seconds, max_retries: 0, retry_backoff_seconds: 0,
        healthcheck_enabled: false, development_only: true,
      });
      onSaved(saved); setMessage("배포 버전을 등록했습니다. 생성 프로파일과 구성을 저장한 뒤 연결을 검사하세요.");
    } catch (error) { setMessage(codexError(error)); } finally { setBusy(false); }
  }
  if (!runners.length) return <p role="status">등록된 Codex runner가 없습니다. 서버의 승인된 실행 설정을 먼저 구성하세요.</p>;
  return <form className="version-form" onSubmit={submit}>
    <h3>Codex 배포 등록</h3>
    <fieldset disabled={busy}>
      <label>서버 runner<select value={runnerRef} onChange={(event) => setRunnerRef(event.target.value)}>{runners.map((item) => <option key={item.runner_ref} value={item.runner_ref}>{item.runner_ref} · CLI {item.cli_version}</option>)}</select></label>
      <label>LLM 모델 정의<select name="model" required>{llms.map((item) => <option key={item.id} value={item.id}>{item.name} v{item.version}</option>)}</select></label>
      {!llms.length ? <p>먼저 LLM 모델 정의를 등록하세요.</p> : null}
      <label>배포 이름<input name="name" required maxLength={180} /></label>
      <label>요청 모델 ID<input name="requestedModel" required maxLength={180} /></label>
      <p>개발 환경 · owner 전용 · OpenAI 외부 처리 · 공식 CLI 인증 · 자동 재시도 없음</p>
      {runner ? <p>시간 제한 {runner.limits.timeout_seconds}초 · 출력 수용 한도 {runner.limits.max_output_tokens} 토큰 · 동시 {runner.limits.max_concurrent}건. 출력 수용 한도는 과금 상한이 아닙니다.</p> : null}
      {!runner?.local_preflight_passed ? <p role="status">로컬 사전점검 필요: {runner?.safe_error_code ?? "runner 미선택"}</p> : null}
    </fieldset>
    <button disabled={busy || !llms.length || !runner?.local_preflight_passed}>Codex 배포 버전 등록</button>
    {message ? <p role="status">{message}</p> : null}
  </form>;
}
