import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { DeploymentRegistry } from "./DeploymentRegistry";
import type { DeploymentSummary } from "./api";

afterEach(() => vi.unstubAllGlobals());

describe("DeploymentRegistry", () => {
  it("shows safe executable Deployment details without internal references", () => {
    const deployment = {
      deployment_id: "deployment-internal-id",
      version_id: "deployment-version-internal-id",
      version: 3,
      display_name: "OpenAI 금융 답변",
      description: "승인된 외부 생성",
      model_name: "OpenAI GPT-5 mini",
      model_version: 2,
      provider: "openai_responses",
      provider_model_id: "gpt-5-mini-2025-08-07",
      location: "external",
      external_transfer: true,
      allowed_environments: ["staging", "production"],
      capabilities: ["structured_output", "contextualization"],
      secret_configured: true,
      readiness: { ready: true, reason_codes: [] },
      latest_health: {
        status: "ready",
        safe_error_code: null,
        observed_provider_model_id: "gpt-5-mini-2025-08-07",
        latency_ms: 84,
        checked_at: "2026-09-05T08:10:00Z",
      },
      secret_ref: "openai-primary",
      endpoint_ref: "openai-responses",
      endpoint: "https://provider.invalid/v1",
      secret: "sk-not-a-real-secret",
    } as DeploymentSummary & Record<string, unknown>;

    render(<DeploymentRegistry deployments={[deployment]} />);

    expect(screen.getByRole("heading", { name: "OpenAI 금융 답변" })).toBeVisible();
    expect(screen.getByText("외부 API")).toBeVisible();
    expect(screen.getByText("gpt-5-mini-2025-08-07")).toBeVisible();
    expect(screen.getByText("OpenAI GPT-5 mini v2")).toBeVisible();
    expect(screen.getByText("인증정보 구성됨")).toBeVisible();
    expect(screen.getByText("구조화 출력")).toBeVisible();
    expect(screen.getByText("후속질문 문맥화")).toBeVisible();
    expect(screen.getByText(/정상.*84ms/)).toBeVisible();
    expect(screen.queryByText("deployment-internal-id")).not.toBeInTheDocument();
    expect(screen.queryByText("deployment-version-internal-id")).not.toBeInTheDocument();
    expect(screen.queryByText("openai-primary")).not.toBeInTheDocument();
    expect(screen.queryByText("openai-responses", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByText(/sk-/)).not.toBeInTheDocument();
    expect(screen.queryByText(/provider\.invalid/)).not.toBeInTheDocument();
  });

  it("filters unsupported providers and explains empty and unavailable states", () => {
    const unsupported = {
      display_name: "미지원 공급자",
      provider: "anthropic",
    } as unknown as DeploymentSummary;
    const unavailable = {
      deployment_id: "local-deployment",
      version_id: "local-deployment-v1",
      version: 1,
      display_name: "사내 생성 모델",
      description: "",
      model_name: "사내 한국어 모델",
      model_version: 1,
      provider: "local_openai_compatible",
      provider_model_id: "local/korean-rag-v1",
      location: "on_premise",
      external_transfer: false,
      allowed_environments: ["development"],
      capabilities: ["structured_output"],
      secret_configured: false,
      readiness: { ready: false, reason_codes: ["deployment_not_ready"] },
      latest_health: null,
    } satisfies DeploymentSummary;

    const { rerender } = render(
      <DeploymentRegistry deployments={[unsupported, unavailable]} />,
    );
    expect(screen.queryByText("미지원 공급자")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "사내 생성 모델" })).toBeVisible();
    expect(screen.getByText("준비되지 않음")).toBeVisible();
    expect(screen.getByText("상태 확인 기록 없음")).toBeVisible();

    rerender(<DeploymentRegistry deployments={[]} />);
    expect(screen.getByRole("status")).toHaveTextContent("등록된 실행 배포가 없습니다");
  });

  it("runs an owner health check and updates only that card from the safe response", async () => {
    const deployment = externalDeployment();
    const response = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      expect(input).toBe(`/api/v1/admin/rag/deployment-versions/${deployment.version_id}/health-check`);
      expect(init?.method).toBe("POST");
      return response.promise;
    }));
    const user = userEvent.setup();
    render(<DeploymentRegistry deployments={[deployment]} />);

    await user.click(screen.getByRole("button", { name: "OpenAI 금융 답변 상태 확인" }));
    expect(screen.getByRole("button", { name: "상태 확인 중…" })).toBeDisabled();
    response.resolve(jsonResponse({
      status: "ready",
      safe_error_code: null,
      provider: "openai_responses",
      provider_model_id: "gpt-5-mini-2025-08-07",
      observed_provider_model_id: "gpt-5-mini-2025-08-07",
      latency_ms: 42,
      checked_at: "2026-09-05T09:00:00Z",
    }));

    expect(await screen.findByText(/마지막 상태: 정상 · 42ms/)).toBeVisible();
    expect(screen.getByText("사용 가능")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("상태 확인을 완료했습니다");
    expect(screen.queryByText(deployment.version_id)).not.toBeInTheDocument();
  });

  it("shows a safe health-check failure without leaking the server message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      error: {
        code: "provider_authentication_failed",
        message: "provider token raw detail",
        correlation_id: "correlation-safe",
      },
    }, 503)));
    const user = userEvent.setup();
    render(<DeploymentRegistry deployments={[externalDeployment()]} />);

    await user.click(screen.getByRole("button", { name: "OpenAI 금융 답변 상태 확인" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("실행 상태를 확인하지 못했습니다");
    expect(screen.queryByText(/provider token raw detail/)).not.toBeInTheDocument();
  });
});

function externalDeployment(): DeploymentSummary {
  return {
    deployment_id: "deployment-internal-id",
    version_id: "deployment-version-internal-id",
    version: 3,
    display_name: "OpenAI 금융 답변",
    description: "승인된 외부 생성",
    model_name: "OpenAI GPT-5 mini",
    model_version: 2,
    provider: "openai_responses",
    provider_model_id: "gpt-5-mini-2025-08-07",
    location: "external",
    external_transfer: true,
    allowed_environments: ["production"],
    capabilities: ["structured_output", "contextualization"],
    secret_configured: true,
    readiness: { ready: false, reason_codes: ["deployment_not_ready"] },
    latest_health: null,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => { resolve = settle; });
  return { promise, resolve };
}
