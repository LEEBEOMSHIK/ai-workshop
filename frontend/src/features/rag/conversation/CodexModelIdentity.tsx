import type { components } from "../../../shared/api/schema";

type Identity = Pick<components["schemas"]["GenerationExecutionResponse"], "provider" | "requested_provider_model_id" | "observed_provider_model_id" | "model_identity_status">;

export function CodexModelIdentity({ execution }: { execution: Identity }) {
  if (execution.provider !== "development_codex_exec") return null;
  return <div className="control-help">
    <p>요청 모델: {execution.requested_provider_model_id ?? "미확인"}</p>
    <p>실제 모델: {execution.observed_provider_model_id ?? "미확인"}</p>
    {execution.model_identity_status === "mismatch" ? <p role="alert">모델 불일치: 요청 모델과 실행 관측이 다릅니다.</p> : null}
    {!execution.observed_provider_model_id ? <p>실제 실행 모델은 미확인입니다. 요청 모델과 같다고 추정하지 않습니다.</p> : null}
  </div>;
}
