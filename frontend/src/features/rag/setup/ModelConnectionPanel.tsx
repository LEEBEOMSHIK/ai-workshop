"use client";

import { useEffect, useId, useRef, useState, type FormEvent } from "react";
import { ApiError } from "../../../shared/api/client";
import { Button } from "../../../shared/ui/Button";
import { ChoiceGroup } from "../../../shared/ui/ChoiceGroup";
import { registerDeployment, registerModelVersion, type DeploymentCreate, type DeploymentSummary, type ModelDefinitionSummary } from "../models/api";
import { loadSetupOptions, type SetupOptions } from "./setup-api";
import { openAiModelCatalog, openAiModels } from "./openai-model-catalog";
import { anthropicModelCatalog, anthropicModels } from "./anthropic-model-catalog";
import styles from "./ModelConnectionPanel.module.css";

const environments = [
  { value: "development", label: "개발" },
  { value: "staging", label: "스테이징" },
  { value: "production", label: "운영" },
] as const;
const capabilities = [
  { value: "structured_output", label: "구조화된 출력", detail: "사용할 답변 JSON 스키마를 지원하고 인용 필드를 반환합니다." },
  { value: "contextualization", label: "문맥 재작성", detail: "제한된 대화 기록과 질문으로 검색 질문을 재작성합니다." },
  { value: "token_accounting", label: "토큰 사용량 기록", detail: "응답에서 입력·출력 토큰 사용량을 제공합니다." },
] as const;

function failureMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return "소유자 권한이 필요합니다. 현재 계정 권한을 확인하세요.";
    if (error.status === 401) return "로그인이 필요합니다. 다시 로그인한 뒤 시도하세요.";
    if (error.code === "unknown_endpoint_reference") return "서버 연결 참조가 변경됐습니다. 서버 설정을 확인하세요.";
    if (error.status === 409) return "이미 저장된 이름·버전인지 기존 목록에서 확인하세요.";
    if (error.status === 422) return "입력값과 서버에 준비된 연결·인증 참조를 확인하세요.";
  }
  return "요청을 완료하지 못했습니다. 기존 목록에서 저장 여부를 확인한 뒤 다시 시도하세요.";
}

export interface ModelConnectionPanelProps {
  models: ModelDefinitionSummary[];
  deployments: DeploymentSummary[];
  selectedDeploymentId: string;
  onModelSaved: (model: ModelDefinitionSummary) => void;
  onDeploymentSaved: (deployment: DeploymentSummary) => void;
  onSelectDeployment: (versionId: string) => void;
}

export function ModelConnectionPanel({ models, deployments, selectedDeploymentId, onModelSaved, onDeploymentSaved, onSelectDeployment }: ModelConnectionPanelProps) {
  const [mode, setMode] = useState("existing");
  const [provider, setProvider] = useState("local");
  const [options, setOptions] = useState<SetupOptions | null>(null);
  const [optionsError, setOptionsError] = useState("");
  const [reload, setReload] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [providerModel, setProviderModel] = useState("");
  const [modelInputMode, setModelInputMode] = useState("catalog");
  const [modelId, setModelId] = useState("");
  const [modelVersion, setModelVersion] = useState("1");
  const [endpoint, setEndpoint] = useState("");
  const [secret, setSecret] = useState("");
  const [confirmedCapabilities, setConfirmedCapabilities] = useState<string[]>([]);
  const [uncertainResult, setUncertainResult] = useState(false);
  const [savedModel, setSavedModel] = useState<ModelDefinitionSummary | null>(null);
  const [savedConnection, setSavedConnection] = useState<DeploymentSummary | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const submitting = useRef(false);
  const formRef = useRef<HTMLFormElement>(null);
  const catalogHelpId = useId();
  const currentSelection = useRef(selectedDeploymentId);
  useEffect(() => { currentSelection.current = selectedDeploymentId; }, [selectedDeploymentId]);

  useEffect(() => {
    const controller = new AbortController();
    loadSetupOptions(controller.signal).then(value => {
      if (!controller.signal.aborted) { setOptions(value); setLoading(false); }
    }).catch(cause => {
      if (!controller.signal.aborted) { setOptionsError(failureMessage(cause)); setLoading(false); }
    });
    return () => controller.abort();
  }, [reload]);

  const external = provider !== "local";
  const claude = provider === "anthropic";
  const providerName = claude ? "Claude" : "OpenAI";
  const recipient = claude ? "Anthropic" : "OpenAI";
  const catalog = claude ? anthropicModelCatalog : openAiModelCatalog;
  const catalogModels = claude ? anthropicModels : openAiModels;
  const noticeRef = claude ? "anthropic-processing-notice-v1" : "openai-processing-notice-v1";
  const catalogModel = external && modelInputMode === "catalog" ? catalogModels.find(item => item.id === providerModel) : undefined;
  const endpoints = options?.endpoints.filter(item => claude ? item.dialect === "anthropic" : external ? item.dialect === "openai" : item.dialect !== "anthropic") ?? [];
  const missingOptions = !endpoints.length || (external && !options?.secret_references.length);
  const identityLocked = busy || uncertainResult || Boolean(savedModel) || Boolean(savedConnection);
  const llms = models.filter(item => item.kind === "llm");

  function changeProvider(value: string) {
    setProvider(value); setEndpoint(""); setSecret(""); setModelInputMode("catalog");
    changeProviderModel("");
  }

  function changeProviderModel(value: string) {
    setProviderModel(value); setModelId(""); setConfirmedCapabilities([]); setError(""); setMessage("");
  }

  function changeModelInputMode(value: string) {
    setModelInputMode(value); changeProviderModel("");
  }

  function startAnother() {
    formRef.current?.reset();
    setName(""); setProviderModel(""); setModelId(""); setModelVersion("1");
    setProvider("local"); setEndpoint(""); setSecret(""); setModelInputMode("catalog");
    setConfirmedCapabilities([]); setUncertainResult(false);
    setSavedModel(null); setSavedConnection(null); setError(""); setMessage("");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current || uncertainResult || savedConnection || loading || !options || missingOptions) return;
    const form = new FormData(event.currentTarget);
    const text = (key: string) => String(form.get(key) ?? "").trim();
    const displayName = name.trim(), providerModelId = providerModel.trim();
    const selectedEnvironments = environments.filter(item => form.getAll("environment").includes(item.value)).map(item => item.value);
    const selectedCapabilities = capabilities.filter(item => form.getAll("capability").includes(item.value)).map(item => item.value);
    const description = text("description"), timeout = Number(text("timeout")), retries = Number(text("retries")), backoff = Number(text("backoff"));
    const location = external ? "external" : text("location");
    setError(""); setMessage("");
    if (external && modelInputMode === "catalog" && !catalogModels.some(item => item.id === providerModelId)) {
      setError(`${providerName} 모델 목록에서 사용할 모델을 선택하세요. 목록 밖 모델은 고급 직접 입력을 사용하세요.`); return;
    }
    if (!displayName || displayName.length > 180 || !providerModelId || providerModelId.length > 180 || description.length > 1000) {
      setError("연결 이름과 정확한 공급자 모델 ID를 입력하고 길이를 확인하세요."); return;
    }
    if (!savedModel && (modelId ? !llms.some(item => item.id === modelId) : !Number.isSafeInteger(Number(modelVersion)) || Number(modelVersion) < 1)) {
      setError("기존 LLM 모델 정의 또는 새 모델 정의의 양수 버전을 확인하세요."); return;
    }
    if (!endpoints.some(item => item.reference === endpoint) || (external && !options.secret_references.includes(secret))) {
      setError("서버에 준비된 연결과 필요한 인증을 선택하세요."); return;
    }
    if (!selectedEnvironments.length || !selectedCapabilities.length || !["local", "on_premise", "external"].includes(location)) {
      setError("허용 환경과 확인한 지원 기능을 각각 하나 이상 선택하고 실행 위치를 확인하세요."); return;
    }
    if (!text("timeout") || !Number.isFinite(timeout) || timeout <= 0 || !text("retries") || !Number.isSafeInteger(retries) || retries < 0 || !text("backoff") || !Number.isFinite(backoff) || backoff < 0) {
      setError("시간 제한은 양수, 재시도 횟수는 0 이상의 정수, 재시도 대기는 0 이상의 수로 입력하세요."); return;
    }
    const originalSelection = selectedDeploymentId;
    let retainedModel = savedModel;
    submitting.current = true; setBusy(true);
    try {
      if (!retainedModel && !modelId) {
        retainedModel = await registerModelVersion({ kind: "llm", name: displayName, version: Number(modelVersion), config: { model_identifier: providerModelId } });
        setSavedModel(retainedModel); onModelSaved(retainedModel);
      }
      const request: DeploymentCreate = {
        display_name: displayName, description, model_definition_id: retainedModel?.id ?? modelId,
        provider: claude ? "anthropic_messages" : external ? "openai_responses" : "local_openai_compatible", provider_model_id: providerModelId,
        endpoint_ref: endpoint, secret_ref: external ? secret : null,
        location: location as DeploymentCreate["location"], allowed_environments: selectedEnvironments, capabilities: selectedCapabilities,
        external_transfer: external,
        transmitted_data_categories: external ? ["question", "bounded_history", "evidence", "service_instructions"] : [],
        data_processing_notice_ref: external ? noticeRef : null,
        timeout_seconds: timeout, max_retries: retries, retry_backoff_seconds: backoff,
        healthcheck_enabled: true, development_only: selectedEnvironments.length === 1 && selectedEnvironments[0] === "development",
      };
      const saved = await registerDeployment(request);
      setSavedConnection(saved); onDeploymentSaved(saved);
      if (currentSelection.current === originalSelection) onSelectDeployment(saved.version_id);
      setMessage("모델 연결을 등록했습니다. 다음 단계에서 RAG 구성을 만들고 연결·품질을 검증하세요.");
    } catch (cause) {
      const uncertain = !(cause instanceof ApiError) || cause.status >= 500 || cause.status === 408;
      setUncertainResult(uncertain);
      setError(uncertain
        ? `${retainedModel ? "모델 정의는 저장됐습니다. " : ""}등록 결과를 확인하지 못했습니다. 중복 저장을 막기 위해 재등록을 잠갔습니다. 화면을 새로고침해 기존 모델·연결 목록에서 저장 여부를 확인하세요.`
        : `${retainedModel ? "모델 정의는 저장됐습니다. 같은 정의로 연결 등록만 다시 시도합니다. " : ""}${failureMessage(cause)}`);
    } finally { submitting.current = false; setBusy(false); }
  }

  return <section className={styles.panel} aria-label="모델 연결">
    <header><h2>1. 모델 연결</h2><p>기존 연결을 선택하거나 로컬·OpenAI·Claude 모델을 등록하세요. 선택과 등록은 모델 추론을 실행하지 않습니다.</p></header>
    <ChoiceGroup legend="연결 방법" value={mode} onChange={setMode} disabled={busy}
      options={[{ value: "existing", label: "기존 연결 선택" }, { value: "new", label: "새 연결 등록" }]} />
    <div hidden={mode !== "existing"}>
      <label className={styles.field}>기존 모델 연결<select value={selectedDeploymentId} disabled={busy} onChange={event => onSelectDeployment(event.target.value)}>
        <option value="">연결을 선택하세요</option>
        {deployments.map(item => <option key={item.version_id} value={item.version_id}>{item.display_name} v{item.version} · {item.provider === "anthropic_messages" ? "Claude" : item.provider === "openai_responses" ? "OpenAI" : item.external_transfer ? "외부" : item.location === "on_premise" ? "사내" : "로컬"} · {item.provider_model_id}</option>)}
      </select></label>
      {!deployments.length ? <p>등록된 연결이 없습니다. 새 연결 등록에서 시작하세요.</p> : null}
    </div>
    {loading ? <p role="status">서버에 준비된 연결을 불러오는 중…</p> : null}
    {optionsError ? <div className={styles.error} role="alert"><p>{optionsError}</p><Button disabled={loading || busy} onClick={() => { setOptionsError(""); setLoading(true); setReload(value => value + 1); }}>연결 목록 다시 불러오기</Button></div> : null}
    <div hidden={mode !== "new"}>
      {options ? <form ref={formRef} aria-label="새 모델 연결 등록" className={styles.form} onSubmit={submit} noValidate>
        <ChoiceGroup legend="공급자" value={provider} onChange={changeProvider} disabled={identityLocked}
          options={[{ value: "local", label: "로컬·사내" }, { value: "openai", label: "OpenAI" }, { value: "anthropic", label: "Claude · Anthropic" }]} />
        <fieldset disabled={identityLocked} className={styles.fields}>
          <legend>모델 식별</legend>
          <label className={styles.field}>연결 이름<input value={name} onChange={event => setName(event.target.value)} maxLength={180} required /></label>
          {external ? <>
            <ChoiceGroup legend={`${providerName} 모델 입력 방식`} value={modelInputMode} onChange={changeModelInputMode} disabled={identityLocked}
              options={[{ value: "catalog", label: "주요 모델 목록" }, { value: "manual", label: "직접 입력 · 고급" }]} />
            <div id={catalogHelpId} className={styles.catalogHelp}>
              <p>주요 공개 텍스트 모델 · 공개일 최신순, 같은 날은 이름순입니다. 성능 순위가 아닙니다.</p>
              <p>공개 카탈로그 확인일: <time dateTime={catalog.verified_at}>{catalog.verified_at}</time>. 계정별 사용 가능 여부는 서버 연결·인증 준비 후 연결 확인이 필요합니다.</p>
              <p>{claude ? "Anthropic 직접 API로 연결합니다. 공급자 기본 생성 설정을 사용하는 Claude 전용 답변 후보를 선택하고, 연결·답변 평가 후 적용하세요." : "공식 API 지원과 이 앱의 실행·품질 수용은 별개입니다. 현재 앱의 생성 파라미터 호환성은 별도 확인이 필요합니다. 연결·답변 평가 후 적용하세요."}</p>
            </div>
          </> : null}
          {external && modelInputMode === "catalog" ? <>
            <label className={styles.field}>{providerName} 모델<select value={providerModel} onChange={event => changeProviderModel(event.target.value)} aria-describedby={catalogHelpId} required>
              <option value="">사용할 {providerName} 모델을 선택하세요</option>
              {catalogModels.map(model => <option key={model.id} value={model.id}>{model.name} · 공개 {model.released_at}</option>)}
            </select></label>
            {catalogModel ? <div className={styles.catalogSelection}>
              <p>선택한 모델 ID: <code>{catalogModel.id}</code></p>
              <p>공개일: <time dateTime={catalogModel.released_at}>{catalogModel.released_at}</time></p>
              <p><a href={catalogModel.documentation_url} target="_blank" rel="noreferrer">선택한 모델 공식 문서</a> · <a href={catalog.release_source_url} target="_blank" rel="noreferrer">공개일 근거</a></p>
              {catalogModel.parameter_notes.map(note => <p className={styles.notice} key={note}>{note}</p>)}
            </div> : null}
          </> : <>
            <label className={styles.field}>공급자 모델 ID<input value={providerModel} onChange={event => changeProviderModel(event.target.value)} maxLength={180} autoComplete="off" required /></label>
            <p className={styles.help}>{external ? "목록 밖 모델은 공식 문서와 계정 사용 권한을 확인한 정확한 모델 ID를 입력하세요." : "서버에 설치된 정확한 모델 ID를 입력하세요."} 모델 ID를 자동 추정하지 않습니다.</p>
          </>}
          <label className={styles.field}>모델 정의<select value={modelId} onChange={event => setModelId(event.target.value)}>
            <option value="">이 연결 이름으로 새 모델 정의 만들기</option>
            {llms.map(item => <option key={item.id} value={item.id}>{item.name} v{item.version}</option>)}
          </select></label>
        </fieldset>
        <fieldset disabled={busy || uncertainResult || Boolean(savedConnection)} className={styles.fields}>
          <legend>서버 연결</legend>
          <label className={styles.field}>서버 연결<select value={endpoint} onChange={event => setEndpoint(event.target.value)} required>
            <option value="">준비된 연결을 선택하세요</option>
            {endpoints.map(item => <option key={item.reference} value={item.reference}>{item.reference} · {item.dialect === "anthropic" ? "Claude Messages API" : item.dialect === "ollama" ? "Ollama" : "OpenAI 호환 HTTP"}</option>)}
          </select></label>
          {external ? <label className={styles.field}>서버 인증<select value={secret} onChange={event => setSecret(event.target.value)} required>
            <option value="">준비된 인증을 선택하세요</option>{options.secret_references.map(reference => <option key={reference} value={reference}>{reference} · 설정됨</option>)}
          </select></label> : <label className={styles.field}>실행 위치<select name="location" defaultValue="local"><option value="local">로컬</option><option value="on_premise">사내</option></select></label>}
          {claude ? <p className={styles.help}>Anthropic의 특정 워크스페이스에 연결된 API 키를 서버 인증으로 준비하세요. 조직 전체 키의 별도 워크스페이스 지정은 현재 지원하지 않습니다.</p> : null}
          <p className={styles.help}>연결 주소·API 키는 서버에서 관리합니다. 이 화면에서는 참조 이름만 선택합니다.{!external ? " 인증이 필요한 로컬 연결은 기존 고급 설정을 확인하세요." : ` 선택한 연결이 승인된 외부 ${recipient} 주소인지 서버 운영자가 확인해야 합니다.`}</p>
          {missingOptions ? <div className={styles.notice} role="status"><p>서버 준비가 필요합니다. 프로젝트 루트 .env 또는 승인된 Secret Manager에서 AI_WORKSHOP_PROVIDER_ENDPOINT_REFS{external ? "와 AI_WORKSHOP_PROVIDER_SECRET_REFS" : ""}를 설정한 뒤 API 프로세스를 재시작하세요.</p><p>준비 절차: <code>docs/runbooks/local-development.md</code>의 “Deployment Registry와 OpenAI Responses 운영”.</p></div> : null}
          {external ? <div className={styles.notice}><p>외부 처리 고지: 질문, 제한된 대화 기록, 문서 근거, 서비스 지침을 {recipient}에 전송합니다. 공개 또는 비식별로 승인된 자료만 사용하세요.</p><p>등록 후에도 회사·지식 공간 데이터 정책과 구성별 명시 승인, 품질 평가가 필요합니다.</p><small>고지 버전: {noticeRef}</small></div> : null}
          <fieldset className={styles.capabilities}><legend>확인한 지원 기능</legend><p className={styles.help}>모델·서버가 실제로 지원하는 기능만 선택하세요. 답변 스키마 호환성과 인용 품질은 다음 단계에서 별도로 검증합니다.</p>
            {capabilities.map(item => <label className={styles.check} key={item.value}><input type="checkbox" name="capability" value={item.value} aria-label={item.label}
              checked={confirmedCapabilities.includes(item.value)} onChange={event => setConfirmedCapabilities(current => event.target.checked ? [...current, item.value] : current.filter(value => value !== item.value))} /><span>{item.label}<small>{item.detail}</small></span></label>)}
          </fieldset>
          <details className={styles.advanced}><summary>고급 설정 · 환경, 버전, 시간 제한</summary><div className={styles.fields}>
            <label className={styles.field}>모델 정의 버전<input value={modelVersion} onChange={event => setModelVersion(event.target.value)} type="number" min={1} step={1} disabled={Boolean(modelId) || Boolean(savedModel)} /></label>
            <label className={styles.field}>연결 설명<textarea name="description" maxLength={1000} /></label>
            <fieldset><legend>허용 환경</legend>{environments.map(item => <label className={styles.check} key={item.value}><input type="checkbox" name="environment" value={item.value} defaultChecked={item.value === options.environment} /><span>{item.label}{item.value === options.environment ? " · 현재 환경" : ""}</span></label>)}</fieldset>
            <label className={styles.field}>시간 제한(초)<input name="timeout" type="number" min={0} step="any" defaultValue={120} required /></label>
            <label className={styles.field}>최대 재시도 횟수<input name="retries" type="number" min={0} step={1} defaultValue={0} required /></label>
            <label className={styles.field}>재시도 대기(초)<input name="backoff" type="number" min={0} step="any" defaultValue={0} required /></label>
          </div></details>
        </fieldset>
        <div className={styles.actions}><Button variant="primary" type="submit" disabled={busy || uncertainResult || loading || missingOptions || Boolean(savedConnection)}>{busy ? "모델 연결 등록 중…" : uncertainResult ? "등록 결과 확인 필요" : savedModel && !savedConnection ? "연결 등록 다시 시도" : "모델 연결 등록"}</Button>
          {savedModel || savedConnection || uncertainResult ? <Button disabled={busy} onClick={startAnother}>다른 연결 등록 시작</Button> : null}</div>
        {error ? <p role="alert" className={styles.error}>{error}</p> : null}
        {message ? <p role="status" className={styles.success}>{message}</p> : null}
        {savedModel && !savedConnection ? <p className={styles.help}>저장된 모델 정의: {savedModel.name} v{savedModel.version}. 다른 연결을 시작해도 이 정의는 기존 목록에 보존됩니다.</p> : null}
      </form> : null}
    </div>
  </section>;
}
