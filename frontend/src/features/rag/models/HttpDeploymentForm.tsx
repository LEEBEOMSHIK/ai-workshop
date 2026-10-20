import { useRef, useState, type FormEvent } from "react";

import { ApiError } from "../../../shared/api/client";
import { registerDeployment, type DeploymentCreate, type DeploymentSummary, type ModelDefinitionSummary } from "./api";

const environments = [
  { value: "development", label: "개발" },
  { value: "staging", label: "스테이징" },
  { value: "production", label: "운영" },
] as const;
const capabilities = [
  { value: "structured_output", label: "구조화된 출력" },
  { value: "contextualization", label: "문맥 재작성" },
  { value: "token_accounting", label: "토큰 사용량 기록" },
] as const;

function failureMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 403) return "배포 등록에는 소유자 권한이 필요합니다. 현재 계정 권한을 확인하세요.";
    if (error.status === 401) return "로그인이 필요합니다. 다시 로그인한 뒤 등록하세요.";
    if (error.code === "unknown_endpoint_reference") return "서버에 등록된 endpoint ref인지 확인하세요. 주소와 dialect 설정은 서버 운영자가 관리합니다.";
    if (error.code === "deployment_version_exists") return "이미 등록된 배포입니다. 배포 목록을 확인하세요.";
    if (error.code === "invalid_model_definition") return "선택한 LLM 모델 정의를 확인하세요.";
    if (error.status === 422) return "배포 입력값을 확인하세요. 서버의 배포 검증을 통과하지 못했습니다.";
  }
  return "요청을 완료하지 못했습니다. 배포 목록에서 등록 여부를 확인한 뒤 다시 시도하세요.";
}

export function HttpDeploymentForm({ models, onSaved }: {
  models: ModelDefinitionSummary[]; onSaved: (value: DeploymentSummary) => void;
}) {
  const submitting = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const llms = models.filter((item) => item.kind === "llm");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting.current) return;
    const form = new FormData(event.currentTarget);
    const text = (name: string) => String(form.get(name) ?? "").trim();
    setError(""); setMessage("");
    const displayName = text("name"), modelId = text("model"), providerModel = text("providerModel");
    const endpoint = text("endpoint"), description = text("description"), location = text("location");
    const selectedEnvironments = environments.filter((item) => form.getAll("environment").includes(item.value)).map((item) => item.value);
    const selectedCapabilities = capabilities.filter((item) => form.getAll("capability").includes(item.value)).map((item) => item.value);
    const timeout = Number(text("timeout")), retries = Number(text("retries")), backoff = Number(text("backoff"));
    if (!llms.some((item) => item.id === modelId) || !displayName || displayName.length > 180 ||
        !providerModel || providerModel.length > 180 || description.length > 1000) {
      setError("LLM 모델 정의, 배포 이름, 공급자 모델 ID와 설명 길이를 확인하세요."); return;
    }
    if (!endpoint || endpoint.length > 120 || /[\s:/\\@?#]/.test(endpoint)) {
      setError("서버 endpoint ref에는 URL이나 인증정보 대신 서버에 등록된 참조 이름만 입력하세요."); return;
    }
    if ((location !== "local" && location !== "on_premise") || !selectedEnvironments.length || !selectedCapabilities.length) {
      setError("실행 위치를 확인하고 허용 환경과 지원 기능을 각각 하나 이상 선택하세요."); return;
    }
    if (!text("timeout") || !Number.isFinite(timeout) || timeout <= 0 ||
        !text("retries") || !Number.isSafeInteger(retries) || retries < 0 ||
        !text("backoff") || !Number.isFinite(backoff) || backoff < 0) {
      setError("시간 제한은 양수, 재시도 횟수는 0 이상의 정수, 재시도 대기는 0 이상의 수로 입력하세요."); return;
    }
    const request: DeploymentCreate = {
      display_name: displayName, description, model_definition_id: modelId,
      provider: "local_openai_compatible", provider_model_id: providerModel, endpoint_ref: endpoint,
      secret_ref: null, location, allowed_environments: selectedEnvironments,
      capabilities: selectedCapabilities, external_transfer: false,
      transmitted_data_categories: [], data_processing_notice_ref: null,
      timeout_seconds: timeout, max_retries: retries, retry_backoff_seconds: backoff,
      healthcheck_enabled: true,
      development_only: selectedEnvironments.length === 1 && selectedEnvironments[0] === "development",
    };
    submitting.current = true; setBusy(true);
    try {
      const saved = await registerDeployment(request);
      setMessage("HTTP 배포 버전을 등록했습니다. 배포 목록에서 상태 확인 후 생성 프로파일과 RAG 구성을 연결하세요.");
      onSaved(saved);
    } catch (cause) { setError(failureMessage(cause)); }
    finally { submitting.current = false; setBusy(false); }
  }

  return <form className="version-form" aria-label="HTTP/Ollama 배포 등록" onSubmit={submit} noValidate>
    <h3>HTTP/Ollama 배포 등록</h3>
    <p>로컬·사내 OpenAI 호환 서버용입니다. 주소와 dialect는 서버 설정에서 관리하며, 여기에는 endpoint ref만 입력합니다. Ollama는 서버에서 해당 참조의 dialect를 ollama로 지정해야 합니다.</p>
    <p>이 폼은 인증정보가 필요 없는 서버를 등록합니다. URL·비밀값은 입력하지 마세요. 등록은 상태 확인이나 추론을 자동 실행하지 않습니다.</p>
    <fieldset disabled={busy}>
      <legend>HTTP 배포 설정</legend>
      <label>HTTP LLM 모델 정의<select name="model" required>{llms.map((item) => <option key={item.id} value={item.id}>{item.name} v{item.version}</option>)}</select></label>
      {!llms.length ? <p>먼저 LLM 모델 정의를 등록하세요.</p> : null}
      <label>HTTP 배포 이름<input name="name" required maxLength={180} /></label>
      <label>HTTP 배포 설명<textarea name="description" maxLength={1000} /></label>
      <label>공급자 모델 ID<input name="providerModel" required maxLength={180} /></label>
      <label>서버 endpoint ref<input name="endpoint" required maxLength={120} autoComplete="off" /></label>
      <label>실행 위치<select name="location" defaultValue="local"><option value="local">로컬</option><option value="on_premise">사내</option></select></label>
      <fieldset><legend>허용 환경</legend>{environments.map((item) => <label key={item.value}><input type="checkbox" name="environment" value={item.value} defaultChecked={item.value === "development"} />{item.label}</label>)}</fieldset>
      <fieldset><legend>서버 지원 기능</legend><p>서버가 지원하는 기능만 선택하세요.</p>{capabilities.map((item) => <label key={item.value}><input type="checkbox" name="capability" value={item.value} defaultChecked />{item.label}</label>)}</fieldset>
      <label>시간 제한(초)<input name="timeout" type="number" min={0} step="any" defaultValue={120} required /></label>
      <label>최대 재시도 횟수<input name="retries" type="number" min={0} step={1} defaultValue={0} required /></label>
      <label>재시도 대기(초)<input name="backoff" type="number" min={0} step="any" defaultValue={0} required /></label>
    </fieldset>
    <button type="submit" disabled={busy || !llms.length}>{busy ? "등록 중…" : "HTTP 배포 버전 등록"}</button>
    {error ? <p role="alert">{error}</p> : null}
    {message ? <p role="status">{message}</p> : null}
  </form>;
}
