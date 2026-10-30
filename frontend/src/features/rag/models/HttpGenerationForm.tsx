import { useId, useRef, useState, type FormEvent } from "react";
import { ChoiceGroup } from "../../../shared/ui/ChoiceGroup";
import { codexError, registerGenerationProfile, type DeploymentSummary, type ProfileSummary } from "./api";

export function HttpGenerationForm({ deployments, onSaved }: {
  deployments: DeploymentSummary[]; onSaved: (value: ProfileSummary) => void;
}) {
  const choices = deployments.filter((item) => ["local_openai_compatible", "openai_responses", "anthropic_messages"].includes(item.provider));
  const [selected, setSelected] = useState("");
  const [executionMode, setExecutionMode] = useState<"direct" | "openai_agents">("direct");
  const [sdkRouting, setSdkRouting] = useState<"manager_delegation" | "autonomous_handoffs">("manager_delegation");
  const [maxModelCalls, setMaxModelCalls] = useState("3");
  const [totalOutputTokens, setTotalOutputTokens] = useState("3072");
  const [handoffModelCalls, setHandoffModelCalls] = useState("3");
  const [maxHandoffs, setMaxHandoffs] = useState("2");
  const [handoffOutputTokens, setHandoffOutputTokens] = useState("3072");
  const [outputTokens, setOutputTokens] = useState("1024");
  const budgetHelpId = useId();
  const [useEvidenceBudget, setUseEvidenceBudget] = useState(false);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const deployment = selected ? choices.find((item) => item.version_id === selected) : choices[0];
  const claude = deployment?.provider === "anthropic_messages";
  const schemaVersion = deployment?.provider === "local_openai_compatible" ? 2 : 1;
  const supportsSdk = deployment?.provider === "local_openai_compatible"
    && deployment.location === "local" && !deployment.external_transfer;
  const sdkSelected = executionMode === "openai_agents";
  const autonomousSelected = sdkSelected && sdkRouting === "autonomous_handoffs";
  const activeModelCalls = autonomousSelected ? handoffModelCalls : maxModelCalls;
  const activeOutputTokens = autonomousSelected ? handoffOutputTokens : totalOutputTokens;
  const reservedOutput = Number(outputTokens) * Number(activeModelCalls);
  const validReservation = Number.isSafeInteger(reservedOutput) && reservedOutput > 0;

  function changeExecutionMode(mode: "direct" | "openai_agents") {
    if (mode === "openai_agents" && !supportsSdk) return;
    setExecutionMode(mode); setError(""); setMessage("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (inFlight.current || !deployment) return;
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim();
    const number = (name: string) => text(name) ? Number(text(name)) : Number.NaN;
    const name = text("name");
    const promptRef = claude ? "rag-answer-v1" : text("promptRef");
    const contextPromptRef = claude ? "rag-contextualize-v1" : text("contextPromptRef");
    const version = number("version");
    const historyTurns = number("historyTurns");
    const historyTokens = number("historyTokens");
    const output = number("output");
    const timeout = number("timeout");
    const temperature = claude ? 1 : number("temperature");
    const evidenceGroups = number("evidenceGroups");
    const evidenceUnits = number("evidenceUnits");
    const evidenceCharacters = number("evidenceCharacters");
    const modelCalls = Number(activeModelCalls);
    const toolCalls = autonomousSelected ? Number(maxHandoffs) : 1;
    const totalOutput = Number(activeOutputTokens);
    setMessage(""); setError("");
    if (sdkSelected && !supportsSdk) {
      setError("선택한 배포에서는 SDK 실행을 지원하지 않습니다. 지원하는 로컬 배포를 선택하거나 직접 실행을 명시적으로 선택하세요.");
      return;
    }
    if (schemaVersion === 1 && useEvidenceBudget) {
      setError("선택한 외부 API의 응답 스키마 1은 문맥 근거 한도를 지원하지 않습니다. 한도 지정을 해제하거나 해당 설정을 지원하는 로컬 배포를 선택하세요.");
      return;
    }
    if (!name || name.length > 180 || !promptRef || !contextPromptRef
      || [version, historyTurns, historyTokens, output].some((value) => !Number.isSafeInteger(value) || value < 1)
      || !Number.isFinite(timeout) || timeout <= 0
      || !Number.isFinite(temperature) || temperature < 0 || temperature > 2) {
      setError("입력을 확인해 주세요. 이름·지침 참조, 양의 정수 한도, 양의 시간 제한과 0~2의 Temperature가 필요합니다.");
      return;
    }
    const validCalls = autonomousSelected
      ? Number.isSafeInteger(modelCalls) && modelCalls >= 2 && modelCalls <= 8
        && Number.isSafeInteger(toolCalls) && toolCalls >= 1 && toolCalls <= 7
      : [2, 3].includes(modelCalls);
    if (sdkSelected && (!validCalls
      || !activeOutputTokens.trim() || !Number.isSafeInteger(totalOutput) || totalOutput < 1 || totalOutput > 2147483647
      || !Number.isSafeInteger(output * modelCalls) || totalOutput < output * modelCalls)) {
      setError(autonomousSelected
        ? "에이전트 모델 호출 한도는 2~8회, 재위임 한도는 1~7회의 정수로 입력하세요. 전체 출력 예약 한도는 호출별 최대 출력 토큰 × 호출 한도 이상, 최대 2147483647 토큰의 정수여야 합니다."
        : "에이전트 모델 호출 한도는 2회 또는 3회, 전체 출력 예약 한도는 호출별 최대 출력 토큰 × 호출 한도 이상의 정수로 입력하세요. 최대 2147483647 토큰입니다.");
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
          generation: { timeout_seconds: timeout, max_output_tokens: output, temperature, response_schema_version: schemaVersion,
            ...(claude ? { sampling_mode: "provider_default" } : {}) },
          ...(sdkSelected ? { orchestration: {
            engine: "openai_agents", version: autonomousSelected ? 2 : 1,
            ...(autonomousSelected ? { dispatch_mode: "autonomous_handoffs" } : {}),
            max_model_calls: modelCalls, max_tool_calls: toolCalls, max_total_output_tokens: totalOutput,
          } } : {}),
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
      <ChoiceGroup legend="에이전트 실행 방식" variant="segmented"
        description="등록할 프로파일의 실행 방식을 선택합니다. 기존 프로파일과 기본 연결은 바뀌지 않습니다."
        value={executionMode} onChange={changeExecutionMode} disabled={busy || !choices.length}
        options={[
          { value: "direct", label: "직접 실행" },
          { value: "openai_agents", label: "OpenAI Agents SDK", disabled: !supportsSdk },
        ]} />
      {sdkSelected ? <ChoiceGroup legend="SDK 담당자 연결 방식" variant="segmented"
        description="관리자 위임은 정해진 답변 담당을 호출합니다. 자율 재위임은 근거·답변·검토 담당이 한도 안에서 다음 담당을 선택합니다."
        value={sdkRouting} onChange={(mode) => { setSdkRouting(mode); setError(""); setMessage(""); }} disabled={busy || !choices.length}
        options={[
          { value: "manager_delegation", label: "관리자 위임" },
          { value: "autonomous_handoffs", label: "자율 재위임" },
        ]} /> : null}
      {deployment && !supportsSdk ? <p className="control-help">선택한 배포에서는 SDK 실행을 지원하지 않습니다. 로컬 OpenAI 호환 배포·외부 전송 없음·응답 스키마 2가 필요합니다.</p> : null}
      <label>HTTP 생성 프로파일 이름<input name="name" maxLength={180} required /></label>
      <label>HTTP 생성 프로파일 버전<input name="version" type="number" min={1} step={1} defaultValue={1} required /></label>
      <div hidden={claude}>
        <label>답변 지침 참조<input name="promptRef" required={!claude} disabled={claude} /></label>
        <label>문맥화 지침 참조<input name="contextPromptRef" required={!claude} disabled={claude} /></label>
      </div>
      {claude ? <p className="control-help">Claude 답변 지침: rag-answer-v1 · 문맥화: rag-contextualize-v1. 근거에 제한된 구조화 답변과 기존 인용 검증을 사용합니다.</p> : null}
      <p className="control-help">서버에 등록된 지침 참조를 입력하세요. 지침 본문·파일 경로·URL을 입력하는 항목이 아닙니다. 등록 후 준비 상태를 확인하세요.</p>
      <label><input type="checkbox" checked={useEvidenceBudget} onChange={(event) => setUseEvidenceBudget(event.target.checked)} />문맥 근거 한도 지정</label>
      <p className="control-help">문맥 근거를 사용하는 답변 지침에는 이 설정이 필요합니다. 해당 지침에서 지원하는 경우에만 선택하세요. 지침과 한도의 호환성은 서버에서 검증합니다.</p>
      {useEvidenceBudget ? <>
        <label>근거 그룹 한도<input name="evidenceGroups" type="number" min={1} step={1} defaultValue={8} required /></label>
        <label>근거 단위 한도<input name="evidenceUnits" type="number" min={1} step={1} defaultValue={32} required /></label>
        <label>근거 문자 수 한도<input name="evidenceCharacters" type="number" min={1} step={1} defaultValue={12000} required /></label>
      </> : null}
      <label>시간 제한 (초)<input name="timeout" type="number" min={0.01} step="any" defaultValue={60} required /></label>
      <label>최대 출력 토큰<input name="output" type="number" min={1} step={1} value={outputTokens} onChange={(event) => setOutputTokens(event.target.value)} required /></label>
      {sdkSelected ? <fieldset>
        <legend>에이전트 실행 예산</legend>
        {autonomousSelected ? <>
          <p className="control-help">첫 질문은 근거 담당과 답변 담당에 최소 모델 2회가 필요합니다. 후속 질문에서 문맥화가 필요하면 1회가 더 필요합니다. 추가 재위임은 모델 호출·재위임 예산을 사용합니다.</p>
          <p className="control-help">선택된 원문 근거만 사용하며 추가 검색은 하지 않습니다. 최종 답변은 인용 검증이 필수입니다.</p>
          <label>전체 모델 호출 한도<input name="maxModelCalls" type="number" min={2} max={8} step={1}
            value={handoffModelCalls} onChange={(event) => setHandoffModelCalls(event.target.value)} required /></label>
          <label>전체 재위임 한도<input name="maxHandoffs" type="number" min={1} max={7} step={1}
            value={maxHandoffs} onChange={(event) => setMaxHandoffs(event.target.value)} required /></label>
        </> : <>
          <p className="control-help">첫 질문은 조정과 답변 생성에 모델 2회가 필요합니다. 후속 질문의 문맥화가 필요하면 최대 3회를 사용합니다.</p>
          <label>전체 모델 호출 한도<select name="maxModelCalls" value={maxModelCalls} onChange={(event) => setMaxModelCalls(event.target.value)} required>
            <option value="2">2회 · 첫 질문</option><option value="3">3회 · 문맥화 포함</option>
          </select></label>
        </>}
        <label>전체 출력 예약 한도 (토큰)<input name="totalOutputTokens" type="number" min={1} max={2147483647} step={1}
          value={activeOutputTokens} onChange={(event) => (autonomousSelected ? setHandoffOutputTokens : setTotalOutputTokens)(event.target.value)} aria-describedby={budgetHelpId} required /></label>
        <p id={budgetHelpId} className="control-help">총출력 예산은 호출별 최대 출력 토큰의 예약 합계를 포함합니다. 현재 설정의 출력 예약 합계: {validReservation ? `${reservedOutput} 토큰` : "입력 확인 필요"}. 출력·호출 한도를 바꿔도 전체 예약 한도 입력값은 유지됩니다.</p>
        <p className="control-help">시간 제한은 문맥화를 포함한 누적 LLM 시간에 적용됩니다. {autonomousSelected ? "모델 호출·재위임 한도에 도달하면 실행을 중단합니다. " : "도구 호출 최대 1회 · "}재시도 0회. 배포의 재시도 설정도 0이어야 하며 서버가 실행 준비 시 검증합니다.</p>
      </fieldset> : null}
      <label>이력 턴 한도<input name="historyTurns" type="number" min={1} step={1} defaultValue={4} required /></label>
      <label>이력 토큰 한도<input name="historyTokens" type="number" min={1} step={1} defaultValue={1024} required /></label>
      <div hidden={claude}><label>Temperature<input name="temperature" type="number" min={0} max={2} step="any" defaultValue={0} required={!claude} disabled={claude} /></label></div>
      {claude ? <p className="control-help">공급자 기본 생성 설정 · Temperature 1.0. Claude API의 기본값을 사용하며 사용자 지정 sampling 값은 전송하지 않습니다.</p> : null}
      <p>응답 스키마 {schemaVersion} · 인용 검증 필수. 등록은 모델 실행·연결 검사·평가 통과 또는 기본값 전환을 수행하지 않습니다.</p>
    </fieldset>
    <button disabled={busy || !deployment || (sdkSelected && !supportsSdk)}>{busy ? "등록 중…" : "HTTP 생성 프로파일 등록"}</button>
    {error ? <p role="alert">{error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
  </form>;
}
