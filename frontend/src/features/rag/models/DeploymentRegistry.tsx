"use client";

import { useState } from "react";

import { checkDeploymentHealth, type DeploymentHealth, type DeploymentSummary } from "./api";

const supportedProviders = new Set(["local_openai_compatible", "openai_responses"]);

const providerLabels: Record<string, string> = {
  local_openai_compatible: "로컬 OpenAI 호환",
  openai_responses: "OpenAI Responses API",
};

const locationLabels: Record<string, string> = {
  local: "로컬",
  on_premise: "사내 온프레미스",
  external: "외부 API",
};

const environmentLabels: Record<string, string> = {
  development: "개발",
  staging: "스테이징",
  production: "운영",
};

const capabilityLabels: Record<string, string> = {
  structured_output: "구조화 출력",
  contextualization: "후속질문 문맥화",
  token_accounting: "토큰 사용량 기록",
};

const readinessLabels: Record<string, string> = {
  deployment_not_allowed_in_environment: "현재 환경에서 사용할 수 없음",
  provider_not_allowed: "회사 정책에서 공급자를 허용하지 않음",
  workspace_external_transfer_denied: "지식 공간 정책에서 외부 전송을 허용하지 않음",
  deployment_not_ready: "실행 준비 확인 필요",
  provider_authentication_failed: "공급자 인증 확인 필요",
  provider_rate_limited: "공급자 요청 한도 초과",
  provider_timeout: "공급자 응답 시간 초과",
  provider_invalid_response: "공급자 응답 확인 필요",
};

export function DeploymentRegistry({ deployments }: { deployments: DeploymentSummary[] }) {
  const supported = deployments.filter((item) => supportedProviders.has(item.provider));
  const [healthByVersion, setHealthByVersion] = useState<Record<string, DeploymentHealth>>({});
  const [checkingVersionId, setCheckingVersionId] = useState<string | null>(null);
  const [healthErrorVersionId, setHealthErrorVersionId] = useState<string | null>(null);
  const [healthSuccessVersionId, setHealthSuccessVersionId] = useState<string | null>(null);

  async function handleHealthCheck(deployment: DeploymentSummary) {
    setCheckingVersionId(deployment.version_id);
    setHealthErrorVersionId(null);
    setHealthSuccessVersionId(null);
    try {
      const health = await checkDeploymentHealth(deployment.version_id);
      setHealthByVersion((current) => ({ ...current, [deployment.version_id]: health }));
      setHealthSuccessVersionId(deployment.version_id);
    } catch {
      setHealthErrorVersionId(deployment.version_id);
    } finally {
      setCheckingVersionId(null);
    }
  }

  return (
    <section className="deployment-registry" aria-labelledby="deployment-registry-title">
      <div className="section-heading-row">
        <div>
          <p className="eyebrow">EXECUTABLE DEPLOYMENTS</p>
          <h2 id="deployment-registry-title">실행 배포</h2>
        </div>
        <p>모델 정의와 달리 실제 환경에서 실행되는 불변 버전입니다.</p>
      </div>
      {supported.length === 0 ? (
        <p role="status">등록된 실행 배포가 없습니다.</p>
      ) : (
        <div className="deployment-grid">
          {supported.map((deployment) => {
            const checkedHealth = healthByVersion[deployment.version_id];
            const readiness = checkedHealth
              ? readinessFromHealth(deployment, checkedHealth)
              : deployment.readiness;
            return (
            <article className="deployment-card" key={deployment.version_id}>
              <div className="configuration-card-heading">
                <div>
                  <p className="deployment-kind">Deployment v{deployment.version}</p>
                  <h3>{deployment.display_name}</h3>
                </div>
                <span className={`location-badge location-${deployment.location}`}>
                  {locationLabels[deployment.location] ?? deployment.location}
                </span>
              </div>
              {deployment.description ? <p>{deployment.description}</p> : null}
              <dl className="identity-list">
                <div><dt>공급자</dt><dd>{providerLabels[deployment.provider]}</dd></div>
                <div><dt>Provider 모델 ID</dt><dd>{deployment.provider_model_id}</dd></div>
                <div><dt>Model Definition</dt><dd>{deployment.model_name} v{deployment.model_version}</dd></div>
                <div>
                  <dt>허용 환경</dt>
                  <dd>{deployment.allowed_environments.map((item) => environmentLabels[item]).join(", ")}</dd>
                </div>
                <div>
                  <dt>기능</dt>
                  <dd className="capability-list">
                    {deployment.capabilities.map((item) => (
                      <span key={item}>{capabilityLabels[item] ?? item}</span>
                    ))}
                  </dd>
                </div>
                <div>
                  <dt>인증정보</dt>
                  <dd>{deployment.secret_configured ? "인증정보 구성됨" : "인증정보 확인 필요"}</dd>
                </div>
                <div>
                  <dt>준비 상태</dt>
                  <dd>{readiness.ready ? "사용 가능" : "준비되지 않음"}</dd>
                </div>
              </dl>
              {!readiness.ready && readiness.reason_codes.length > 0 ? (
                <p className="configuration-readiness" role="status">
                  {readiness.reason_codes.map(readinessReason).join(", ")}
                </p>
              ) : null}
              <HealthStatus health={checkedHealth ?? deployment.latest_health} />
              <button
                type="button"
                aria-label={checkingVersionId === deployment.version_id
                  ? "상태 확인 중…"
                  : `${deployment.display_name} 상태 확인`}
                disabled={checkingVersionId !== null}
                onClick={() => void handleHealthCheck(deployment)}
              >
                {checkingVersionId === deployment.version_id ? "상태 확인 중…" : "상태 확인"}
              </button>
              {healthSuccessVersionId === deployment.version_id ? (
                <p className="form-success" role="status">상태 확인을 완료했습니다.</p>
              ) : null}
              {healthErrorVersionId === deployment.version_id ? (
                <p className="form-error" role="alert">실행 상태를 확인하지 못했습니다.</p>
              ) : null}
            </article>
          );})}
        </div>
      )}
    </section>
  );
}

function readinessFromHealth(
  deployment: DeploymentSummary,
  health: DeploymentHealth,
): DeploymentSummary["readiness"] {
  const ready = health.status === "ready"
    && health.safe_error_code === null
    && health.observed_provider_model_id === deployment.provider_model_id;
  return {
    ready,
    reason_codes: ready ? [] : [health.safe_error_code ?? "deployment_not_ready"],
  };
}

function HealthStatus({ health }: { health: DeploymentSummary["latest_health"] }) {
  if (!health) return <p className="deployment-health" role="status">상태 확인 기록 없음</p>;
  const status = health.status === "ready" || health.status === "healthy" ? "정상" : "확인 필요";
  const latency = health.latency_ms === null ? "응답 시간 미측정" : `${health.latency_ms}ms`;
  return (
    <p className="deployment-health">
      마지막 상태: {status} · {latency} · {formatHealthTime(health.checked_at)}
      {health.safe_error_code ? ` · ${readinessReason(health.safe_error_code)}` : ""}
    </p>
  );
}

function readinessReason(reason: string): string {
  return readinessLabels[reason] ?? "실행 준비 상태를 확인해 주세요";
}

function formatHealthTime(value: string): string {
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? "확인 시각 없음" : parsed.toLocaleString("ko-KR");
}
