import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { HttpDeploymentForm } from "./HttpDeploymentForm";
import type { DeploymentSummary, ModelDefinitionSummary } from "./api";

const models: ModelDefinitionSummary[] = [
  { id: "llm-id", kind: "llm", name: "Synthetic LLM", version: 1, config: {} },
  { id: "embedding-id", kind: "embedding", name: "Embedding only", version: 1, config: {} },
];
const deployment: DeploymentSummary = {
  deployment_id: "deployment-id", version_id: "version-id", version: 1,
  display_name: "Synthetic HTTP", description: "Synthetic description",
  model_name: "Synthetic LLM", model_version: 1, provider: "local_openai_compatible",
  provider_model_id: "synthetic-model:tag", location: "local", external_transfer: false,
  allowed_environments: ["development"], capabilities: ["structured_output"],
  secret_configured: false, readiness: { ready: false, reason_codes: ["deployment_not_ready"] },
  latest_health: null,
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "content-type": "application/json" },
});
afterEach(() => vi.unstubAllGlobals());

function fill() {
  fireEvent.change(screen.getByLabelText("HTTP 배포 이름"), { target: { value: "  Synthetic HTTP  " } });
  fireEvent.change(screen.getByLabelText("HTTP 배포 설명"), { target: { value: " Synthetic description " } });
  fireEvent.change(screen.getByLabelText("공급자 모델 ID"), { target: { value: " synthetic-model:tag " } });
  fireEvent.change(screen.getByLabelText("서버 endpoint ref"), { target: { value: " local-test " } });
}
function submit() { fireEvent.submit(screen.getByRole("form", { name: "HTTP/Ollama 배포 등록" })); }

it("registers a local HTTP deployment only after explicit submission, without health or inference", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json(deployment));
  vi.stubGlobal("fetch", fetcher);
  const onSaved = vi.fn();
  render(<HttpDeploymentForm models={models} onSaved={onSaved} />);
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.queryByRole("option", { name: /Embedding only/ })).not.toBeInTheDocument();
  expect(screen.getByText(/주소와 dialect는 서버 설정/)).toBeVisible();
  fill(); submit();
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(deployment));
  expect(fetcher).toHaveBeenCalledTimes(1);
  const [path, init] = fetcher.mock.calls[0];
  expect(path).toBe("/api/v1/admin/rag/deployments");
  expect(init).toMatchObject({ method: "POST", credentials: "include" });
  expect(JSON.parse(String(init?.body))).toEqual({
    display_name: "Synthetic HTTP", description: "Synthetic description", model_definition_id: "llm-id",
    provider: "local_openai_compatible", provider_model_id: "synthetic-model:tag",
    endpoint_ref: "local-test", secret_ref: null, location: "local",
    allowed_environments: ["development"], development_only: true,
    capabilities: ["structured_output", "contextualization", "token_accounting"],
    external_transfer: false, transmitted_data_categories: [], data_processing_notice_ref: null,
    timeout_seconds: 120, max_retries: 0, retry_backoff_seconds: 0, healthcheck_enabled: true,
  });
  expect(await screen.findByRole("status")).toHaveTextContent(/등록했습니다/);
});

it("accepts explicit on-premise environment and runtime limits", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json(deployment)); vi.stubGlobal("fetch", fetcher);
  render(<HttpDeploymentForm models={models} onSaved={() => {}} />); fill();
  fireEvent.change(screen.getByLabelText("실행 위치"), { target: { value: "on_premise" } });
  fireEvent.click(screen.getByLabelText("운영"));
  fireEvent.change(screen.getByLabelText("시간 제한(초)"), { target: { value: "240.5" } });
  fireEvent.change(screen.getByLabelText("최대 재시도 횟수"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("재시도 대기(초)"), { target: { value: "1.5" } });
  fireEvent.click(screen.getByLabelText("토큰 사용량 기록")); submit();
  await screen.findByRole("status");
  expect(JSON.parse(String(fetcher.mock.calls[0][1]?.body))).toMatchObject({
    location: "on_premise", allowed_environments: ["development", "production"], development_only: false,
    timeout_seconds: 240.5, max_retries: 2, retry_backoff_seconds: 1.5,
    capabilities: ["structured_output", "contextualization"],
  });
});

it.each([
  ["HTTP 배포 이름", "   "], ["공급자 모델 ID", " "], ["서버 endpoint ref", ""],
  ["서버 endpoint ref", "http://127.0.0.1:11434"], ["서버 endpoint ref", "//localhost"],
  ["시간 제한(초)", "0"], ["시간 제한(초)", ""], ["최대 재시도 횟수", "1.5"],
  ["최대 재시도 횟수", "-1"], ["재시도 대기(초)", "-1"],
])("rejects invalid %s (%s) before sending", (label, value) => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<HttpDeploymentForm models={models} onSaved={() => {}} />); fill();
  fireEvent.change(screen.getByLabelText(label), { target: { value } }); submit();
  expect(screen.getByRole("alert")).toBeVisible(); expect(fetcher).not.toHaveBeenCalled();
});

it.each(["environments", "capabilities"])("requires a nonempty %s selection", (kind) => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<HttpDeploymentForm models={models} onSaved={() => {}} />); fill();
  const labels = kind === "environments" ? ["개발"] : ["구조화된 출력", "문맥 재작성", "토큰 사용량 기록"];
  labels.forEach((label) => fireEvent.click(screen.getByLabelText(label))); submit();
  expect(screen.getByRole("alert")).toBeVisible(); expect(fetcher).not.toHaveBeenCalled();
});

it("requires an existing LLM definition", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<HttpDeploymentForm models={models.slice(1)} onSaved={() => {}} />);
  expect(screen.getByText(/먼저 LLM 모델 정의를 등록/)).toBeVisible();
  expect(screen.getByRole("button", { name: "HTTP 배포 버전 등록" })).toBeDisabled();
  submit(); expect(fetcher).not.toHaveBeenCalled();
});

it.each([
  [403, "owner_required", "소유자 권한"],
  [422, "unknown_endpoint_reference", "서버에 등록된 endpoint ref"],
  [409, "deployment_version_exists", "이미 등록"],
  [500, "internal_error", "요청을 완료하지 못했습니다"],
])("handles %s %s safely and retains form input", async (status, code, message) => {
  const fetcher = vi.fn<typeof fetch>(async () => json({ error: { code, message: "secret-sensitive-detail", correlation_id: "synthetic" } }, status));
  vi.stubGlobal("fetch", fetcher); const saved = vi.fn();
  render(<HttpDeploymentForm models={models} onSaved={saved} />); fill(); submit();
  expect(await screen.findByRole("alert")).toHaveTextContent(message);
  expect(screen.queryByText(/secret-sensitive-detail/)).not.toBeInTheDocument();
  expect(screen.getByLabelText("HTTP 배포 이름")).toHaveValue("  Synthetic HTTP  ");
  expect(screen.getByRole("button", { name: "HTTP 배포 버전 등록" })).toBeEnabled();
  expect(saved).not.toHaveBeenCalled(); expect(fetcher).toHaveBeenCalledTimes(1);
});

it("blocks repeated submissions while the request is pending", async () => {
  let complete!: (value: Response) => void;
  const response = new Promise<Response>((resolve) => { complete = resolve; });
  const fetcher = vi.fn<typeof fetch>(() => response); vi.stubGlobal("fetch", fetcher);
  const saved = vi.fn(); render(<HttpDeploymentForm models={models} onSaved={saved} />); fill();
  act(() => { submit(); submit(); });
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "등록 중…" })).toBeDisabled();
  await act(async () => complete(json(deployment)));
  expect(saved).toHaveBeenCalledTimes(1);
});
