import { render, screen } from "@testing-library/react";

import { DeploymentRegistry } from "./DeploymentRegistry";
import type { DeploymentSummary } from "./api";

it.each([
  ["provider_busy", "로컬 모델이 다른 요청을 처리 중입니다. 잠시 후 다시 시도해 주세요."],
  ["provider_input_too_large", "로컬 모델의 입력 한도를 초과했습니다. 질문이나 검색 근거 범위를 줄여 주세요."],
])("shows a local deployment and explains %s", (code, message) => {
  const deployment = {
    deployment_id: "local-deployment", version_id: "local-version", version: 1,
    display_name: "Local text generation", description: "", model_name: "Local test",
    model_version: 1, provider: "local_transformers", provider_model_id: "example/model",
    local_model_ref: "local-text-v1", location: "local", external_transfer: false,
    allowed_environments: ["development"], capabilities: ["structured_output"],
    secret_configured: false, readiness: { ready: false, reason_codes: [code] },
    latest_health: null,
  } satisfies DeploymentSummary;
  render(<DeploymentRegistry deployments={[deployment]} readOnly />);
  expect(screen.getByRole("heading", { name: "Local text generation" })).toBeVisible();
  expect(screen.getByText("로컬 Transformers")).toBeVisible();
  expect(screen.getByText("인증정보 불필요")).toBeVisible();
  expect(screen.getByText(message)).toBeVisible();
  expect(screen.queryByText("local-text-v1")).not.toBeInTheDocument();
});
