import { render, screen } from "@testing-library/react";
import { CodexModelIdentity } from "./CodexModelIdentity";

it("does not infer observed identity from the requested model", () => {
  const { rerender } = render(<CodexModelIdentity execution={{ provider: "development_codex_exec", requested_provider_model_id: "requested-model", observed_provider_model_id: null, model_identity_status: "unknown" }} />);
  expect(screen.getByText("요청 모델: requested-model")).toBeVisible();
  expect(screen.getByText("실제 모델: 미확인")).toBeVisible();
  expect(screen.getByText("실제 실행 모델은 미확인입니다. 요청 모델과 같다고 추정하지 않습니다.")).toBeVisible();
  expect(screen.queryByText(/실행에서 모델 식별자가 관측되지 않았습니다/)).not.toBeInTheDocument();
  rerender(<CodexModelIdentity execution={{ provider: "development_codex_exec", requested_provider_model_id: "requested-model", observed_provider_model_id: "different-model", model_identity_status: "mismatch" }} />);
  expect(screen.getByText("실제 모델: different-model")).toBeVisible();
  expect(screen.getByText(/모델 불일치/)).toBeVisible();
});
