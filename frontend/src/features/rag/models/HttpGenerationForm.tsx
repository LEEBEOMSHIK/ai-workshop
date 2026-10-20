import { useRef, useState, type FormEvent } from "react";
import { codexError, registerGenerationProfile, type DeploymentSummary, type ProfileSummary } from "./api";

export function HttpGenerationForm({ deployments, onSaved }: {
  deployments: DeploymentSummary[]; onSaved: (value: ProfileSummary) => void;
}) {
  const choices = deployments.filter((item) => item.provider === "local_openai_compatible" || item.provider === "openai_responses");
  const [selected, setSelected] = useState("");
  const [useEvidenceBudget, setUseEvidenceBudget] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const deployment = selected ? choices.find((item) => item.version_id === selected) : choices[0];

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current || !deployment) return;
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim();
    const number = (name: string) => text(name) ? Number(text(name)) : Number.NaN;
    const name = text("name");
    const promptRef = text("promptRef");
    const contextPromptRef = text("contextPromptRef");
    const version = number("version");
    const historyTurns = number("historyTurns");
    const historyTokens = number("historyTokens");
    const output = number("output");
    const timeout = number("timeout");
    const temperature = number("temperature");
    const evidenceGroups = number("evidenceGroups");
    const evidenceUnits = number("evidenceUnits");
    const evidenceCharacters = number("evidenceCharacters");
    setMessage(""); setError("");
    if (!name || name.length > 180 || !promptRef || !contextPromptRef
      || [version, historyTurns, historyTokens, output].some((value) => !Number.isSafeInteger(value) || value < 1)
      || !Number.isFinite(timeout) || timeout <= 0
      || !Number.isFinite(temperature) || temperature < 0 || temperature > 2) {
      setError("입력을 확인해 주세요. 이름·지침 참조, 양의 정수 한도, 양의 시간 제한과 0~2의 Temperature가 필요합니다.");
      return;
    }
    if (useEvidenceBudget && ([evidenceGroups, evidenceUnits, evidenceCharacters]
      .some((value) => !Number.isSafeInteger(value) || value < 1) || evidenceGroups > evidenceUnits)) {
      setError("근거 한도는 양의 정수로 입력하고, 그룹 한도를 단위 한도 이하로 지정해 주세요.");
      return;
    }
    inFlight.current = true; setBusy(true);
    try {
      const saved = await registerGenerationProfile({
        name, version, deployment_version_id: deployment.version_id, bindings: [], evaluation_state: "draft",
        config: {
          prompt_ref: promptRef, context_prompt_ref: contextPromptRef, citation_mode: "required",
          ...(useEvidenceBudget ? { context_evidence: {
            version: 1, max_groups: evidenceGroups, max_units: evidenceUnits, max_characters: evidenceCharacters,
          } } : {}),
          context_policy: { max_history_turns: historyTurns, max_history_tokens: historyTokens },
          generation: { timeout_seconds: timeout, max_output_tokens: output, temperature, response_schema_version: 2 },
        },
      });
      onSaved(saved);
      setMessage("생성 프로파일을 등록했습니다. 구성 스튜디오에서 이 프로파일을 선택해 시험 구성을 저장하세요.");
    } catch (cause) {
      setError(codexError(cause));
    } finally {
      inFlight.current = false; setBusy(false);
    }
  }

  return <form className="version-form" onSubmit={submit}>
    <h3>HTTP 생성 프로파일</h3>
    <p>Ollama 등 등록된 HTTP 배포 버전에 답변 설정을 연결합니다. 주소와 인증 정보는 배포의 서버 설정을 사용합니다.</p>
    {!choices.length ? <p>등록된 HTTP 배포가 없습니다. 모델·실행 환경 설정에서 HTTP 배포를 먼저 등록하세요.</p> : null}
    <fieldset disabled={busy || !choices.length}>
      <label>HTTP 배포 버전<select value={deployment?.version_id ?? ""} onChange={(event) => setSelected(event.target.value)} required>
        {!deployment ? <option value="">HTTP 배포를 선택하세요</option> : null}
        {choices.map((item) => <option key={item.version_id} value={item.version_id}>{item.display_name} v{item.version} · {item.provider_model_id}</option>)}
      </select></label>
      <label>HTTP 생성 프로파일 이름<input name="name" maxLength={180} required /></label>
      <label>HTTP 생성 프로파일 버전<input name="version" type="number" min={1} step={1} defaultValue={1} required /></label>
      <label>답변 지침 참조<input name="promptRef" required /></label>
      <label>문맥화 지침 참조<input name="contextPromptRef" required /></label>
      <p className="control-help">서버에 등록된 지침 참조를 입력하세요. 지침 본문·파일 경로·URL을 입력하는 항목이 아닙니다. 등록 후 준비 상태를 확인하세요.</p>
      <label><input type="checkbox" checked={useEvidenceBudget} onChange={(event) => setUseEvidenceBudget(event.target.checked)} />문맥 근거 한도 지정</label>
      <p className="control-help">문맥 근거를 사용하는 답변 지침에는 이 설정이 필요합니다. 해당 지침에서 지원하는 경우에만 선택하세요. 지침과 한도의 호환성은 서버에서 검증합니다.</p>
      {useEvidenceBudget ? <>
        <label>근거 그룹 한도<input name="evidenceGroups" type="number" min={1} step={1} defaultValue={8} required /></label>
        <label>근거 단위 한도<input name="evidenceUnits" type="number" min={1} step={1} defaultValue={32} required /></label>
        <label>근거 문자 수 한도<input name="evidenceCharacters" type="number" min={1} step={1} defaultValue={12000} required /></label>
      </> : null}
      <label>시간 제한 (초)<input name="timeout" type="number" min={0.01} step="any" defaultValue={60} required /></label>
      <label>최대 출력 토큰<input name="output" type="number" min={1} step={1} defaultValue={1024} required /></label>
      <label>이력 턴 한도<input name="historyTurns" type="number" min={1} step={1} defaultValue={4} required /></label>
      <label>이력 토큰 한도<input name="historyTokens" type="number" min={1} step={1} defaultValue={1024} required /></label>
      <label>Temperature<input name="temperature" type="number" min={0} max={2} step="any" defaultValue={0} required /></label>
      <p>응답 스키마 2 · 인용 검증 필수. 등록은 모델 실행·연결 검사·평가 통과 또는 기본값 전환을 수행하지 않습니다.</p>
    </fieldset>
    <button disabled={busy || !deployment}>{busy ? "등록 중…" : "HTTP 생성 프로파일 등록"}</button>
    {error ? <p role="alert">{error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
  </form>;
}
