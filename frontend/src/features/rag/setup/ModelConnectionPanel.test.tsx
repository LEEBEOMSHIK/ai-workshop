import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import { ModelConnectionPanel } from "./ModelConnectionPanel";
import type { DeploymentSummary, ModelDefinitionSummary } from "../models/api";

const models: ModelDefinitionSummary[] = [
  { id: "llm-id", kind: "llm", name: "Existing LLM", version: 2, config: { model_identifier: "existing-model" } },
  { id: "embedding-id", kind: "embedding", name: "Embedding only", version: 1, config: {} },
];
const createdModel: ModelDefinitionSummary = { id: "new-model", kind: "llm", name: "My connection", version: 1, config: { model_identifier: "exact-model-id" } };
const deployment: DeploymentSummary = {
  deployment_id: "deployment-id", version_id: "version-id", version: 1,
  display_name: "Existing connection", description: "Synthetic connection",
  model_name: "Existing LLM", model_version: 2, provider: "local_openai_compatible",
  provider_model_id: "existing-model", location: "local", external_transfer: false,
  allowed_environments: ["staging"], capabilities: ["structured_output"],
  secret_configured: false, readiness: { ready: false, reason_codes: ["deployment_not_ready"] }, latest_health: null,
};
const savedDeployment: DeploymentSummary = { ...deployment, version_id: "new-deployment", display_name: "My connection" };
const options = {
  endpoints: [{ reference: "local-server", dialect: "ollama" }, { reference: "approved-api", dialect: "openai" }],
  secret_references: ["approved-key"], environment: "staging", generation_presets: [],
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
type Write = { path: string; body: Record<string, unknown> };

function mockServer(handler?: (write: Write, count: number) => Promise<Response> | Response, setup: unknown = options) {
  const writes: Write[] = [];
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (path === "/api/v1/admin/rag/deployment-setup-options") return json(setup);
    if (init?.method !== "POST") throw new Error(`Unexpected request ${path}`);
    const write = { path, body: JSON.parse(String(init.body)) as Record<string, unknown> };
    writes.push(write);
    return handler ? handler(write, writes.length) : json(path.endsWith("/models") ? createdModel : savedDeployment);
  });
  vi.stubGlobal("fetch", fetcher);
  return { writes, fetcher };
}

function panel() {
  const callbacks = { onModelSaved: vi.fn(), onDeploymentSaved: vi.fn(), onSelectDeployment: vi.fn() };
  render(<ModelConnectionPanel models={models} deployments={[deployment]} selectedDeploymentId="" {...callbacks} />);
  return callbacks;
}
async function fillNew(provider: "local" | "openai" = "local") {
  fireEvent.click(screen.getByLabelText("새 연결 등록"));
  await screen.findByRole("option", { name: /local-server/ });
  if (provider === "openai") fireEvent.click(screen.getByLabelText("OpenAI"));
  fireEvent.change(screen.getByLabelText("연결 이름"), { target: { value: "  My connection  " } });
  if (provider === "openai") fireEvent.change(screen.getByLabelText("OpenAI 모델"), { target: { value: "gpt-6.1-terra" } });
  else fireEvent.change(screen.getByLabelText("공급자 모델 ID"), { target: { value: "  exact-model-id  " } });
  fireEvent.change(screen.getByLabelText("서버 연결"), { target: { value: provider === "openai" ? "approved-api" : "local-server" } });
  if (provider === "openai") fireEvent.change(screen.getByLabelText("서버 인증"), { target: { value: "approved-key" } });
  fireEvent.click(screen.getByLabelText(/구조화된 출력/));
}
const submit = () => fireEvent.submit(screen.getByRole("form", { name: "새 모델 연결 등록" }));
afterEach(() => vi.unstubAllGlobals());

it("registers Claude through its own dialect and notice without sending prompts", async () => {
  const server = mockServer(undefined, { ...options, endpoints: [...options.endpoints, { reference: "claude-api", dialect: "anthropic" }] });
  const callbacks = panel();
  fireEvent.click(screen.getByLabelText("새 연결 등록"));
  await screen.findByLabelText("Claude · Anthropic");
  fireEvent.click(screen.getByLabelText("Claude · Anthropic"));
  const select = screen.getByLabelText("Claude 모델");
  expect(select).toHaveValue("");
  expect(within(select).getAllByRole("option").slice(1).map(item => item.getAttribute("value")))
    .toEqual(["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"]);
  expect(screen.queryByRole("option", { name: /local-server|approved-api/ })).not.toBeInTheDocument();
  fireEvent.change(select, { target: { value: "claude-sonnet-5-5" } });
  fireEvent.change(screen.getByLabelText("연결 이름"), { target: { value: "Claude candidate" } });
  fireEvent.change(screen.getByLabelText("서버 연결"), { target: { value: "claude-api" } });
  fireEvent.change(screen.getByLabelText("서버 인증"), { target: { value: "approved-key" } });
  fireEvent.click(screen.getByLabelText("구조화된 출력"));
  expect(server.writes).toEqual([]);
  submit();
  await waitFor(() => expect(callbacks.onDeploymentSaved).toHaveBeenCalled());
  expect(server.writes[1].body).toMatchObject({ provider: "anthropic_messages", provider_model_id: "claude-sonnet-5-5",
    location: "external", external_transfer: true, endpoint_ref: "claude-api", secret_ref: "approved-key",
    data_processing_notice_ref: "anthropic-processing-notice-v1", max_retries: 0 });
});

it("clears provider identity and capabilities between OpenAI and Claude and keeps missing refs blocked", async () => {
  const server = mockServer(); panel(); await fillNew("openai");
  fireEvent.click(screen.getByLabelText("Claude · Anthropic"));
  expect(screen.getByLabelText("Claude 모델")).toHaveValue("");
  expect(screen.getByLabelText("구조화된 출력")).not.toBeChecked();
  expect(screen.getByLabelText("서버 연결")).toHaveValue("");
  expect(screen.getByLabelText("서버 인증")).toHaveValue("");
  expect(screen.getByRole("button", { name: "모델 연결 등록" })).toBeDisabled();
  submit(); expect(server.writes).toEqual([]);
  fireEvent.click(screen.getByLabelText("로컬·사내"));
  expect(screen.queryByRole("option", { name: /Claude Messages/ })).not.toBeInTheDocument();
});

it("selects an existing connection without creating or probing a model", async () => {
  const server = mockServer(); const callbacks = panel();
  fireEvent.change(screen.getByLabelText("기존 모델 연결"), { target: { value: "version-id" } });
  expect(callbacks.onSelectDeployment).toHaveBeenCalledWith("version-id");
  await waitFor(() => expect(server.fetcher).toHaveBeenCalledTimes(1));
  expect(server.writes).toEqual([]);
});

it("creates a local model and connection with exact user input and the current environment", async () => {
  const server = mockServer(); const callbacks = panel(); await fillNew();
  expect(screen.getByLabelText("토큰 사용량 기록")).not.toBeChecked();
  expect(screen.getByLabelText("문맥 재작성")).not.toBeChecked();
  fireEvent.change(screen.getByLabelText("실행 위치"), { target: { value: "on_premise" } });
  submit();
  await waitFor(() => expect(callbacks.onSelectDeployment).toHaveBeenCalledWith("new-deployment"));
  expect(server.writes).toEqual([
    { path: "/api/v1/admin/rag/models", body: { kind: "llm", name: "My connection", version: 1, config: { model_identifier: "exact-model-id" } } },
    { path: "/api/v1/admin/rag/deployments", body: {
      display_name: "My connection", description: "", model_definition_id: "new-model",
      provider: "local_openai_compatible", provider_model_id: "exact-model-id", endpoint_ref: "local-server", secret_ref: null,
      location: "on_premise", allowed_environments: ["staging"], capabilities: ["structured_output"],
      external_transfer: false, transmitted_data_categories: [], data_processing_notice_ref: null,
      timeout_seconds: 120, max_retries: 0, retry_backoff_seconds: 0, healthcheck_enabled: true, development_only: false,
    } },
  ]);
  expect(callbacks.onModelSaved).toHaveBeenCalledWith(createdModel);
  expect(callbacks.onDeploymentSaved).toHaveBeenCalledWith(savedDeployment);
  submit(); expect(server.writes).toHaveLength(2);
});

it("registers OpenAI with the complete external transfer notice and prepared refs only", async () => {
  const server = mockServer(); const callbacks = panel(); await fillNew("openai");
  expect(screen.queryByRole("option", { name: /local-server/ })).not.toBeInTheDocument();
  expect(screen.getByText(/서비스 지침/)).toBeVisible();
  submit();
  await waitFor(() => expect(callbacks.onDeploymentSaved).toHaveBeenCalled());
  expect(server.writes[1].body).toMatchObject({
    provider: "openai_responses", location: "external", external_transfer: true,
    endpoint_ref: "approved-api", secret_ref: "approved-key",
    transmitted_data_categories: ["question", "bounded_history", "evidence", "service_instructions"],
    data_processing_notice_ref: "openai-processing-notice-v1", allowed_environments: ["staging"],
    provider_model_id: "gpt-6.1-terra",
  });
  expect(server.writes[0].body.config).toEqual({ model_identifier: "gpt-6.1-terra" });
  expect(screen.queryByLabelText(/API 키|URL/)).not.toBeInTheDocument();
});

it("reuses an explicitly selected LLM definition without creating another model", async () => {
  const server = mockServer(); const callbacks = panel(); await fillNew();
  fireEvent.change(screen.getByLabelText("모델 정의"), { target: { value: "llm-id" } });
  expect(screen.queryByRole("option", { name: /Embedding only/ })).not.toBeInTheDocument();
  submit(); await waitFor(() => expect(callbacks.onDeploymentSaved).toHaveBeenCalled());
  expect(server.writes).toHaveLength(1);
  expect(server.writes[0].body.model_definition_id).toBe("llm-id");
  expect(callbacks.onModelSaved).not.toHaveBeenCalled();
});

it("retains a created model after connection failure and retries only the connection", async () => {
  const server = mockServer((write, count) => count === 2 ? json({ error: { code: "unknown_endpoint_reference", message: "sensitive server detail", correlation_id: "test" } }, 422) : json(write.path.endsWith("/models") ? createdModel : savedDeployment));
  const callbacks = panel(); await fillNew(); submit();
  expect(await screen.findByRole("alert")).toHaveTextContent(/모델 정의는 저장/);
  expect(screen.queryByText(/sensitive server detail/)).not.toBeInTheDocument();
  expect(screen.getByLabelText("공급자 모델 ID")).toBeDisabled();
  expect(screen.getByLabelText("OpenAI")).toBeDisabled();
  expect(screen.getByLabelText("연결 이름")).toHaveValue("  My connection  ");
  fireEvent.click(screen.getByLabelText("기존 연결 선택"));
  fireEvent.click(screen.getByLabelText("새 연결 등록"));
  submit(); await waitFor(() => expect(callbacks.onDeploymentSaved).toHaveBeenCalled());
  expect(server.writes.map(write => write.path)).toEqual(["/api/v1/admin/rag/models", "/api/v1/admin/rag/deployments", "/api/v1/admin/rag/deployments"]);
  expect(server.writes[2].body.model_definition_id).toBe("new-model");
  expect(callbacks.onModelSaved).toHaveBeenCalledTimes(1);
});

it("locks scope and rejects repeated submits during registration", async () => {
  let complete!: (response: Response) => void;
  const pending = new Promise<Response>(resolve => { complete = resolve; });
  const server = mockServer(write => write.path.endsWith("/models") ? pending : json(savedDeployment));
  const callbacks = panel(); await fillNew();
  act(() => { submit(); submit(); });
  expect(server.writes).toHaveLength(1);
  expect(screen.getByLabelText("OpenAI")).toBeDisabled();
  expect(screen.getByLabelText("기존 연결 선택")).toBeDisabled();
  await act(async () => complete(json(createdModel)));
  await waitFor(() => expect(callbacks.onDeploymentSaved).toHaveBeenCalledTimes(1));
  expect(server.writes).toHaveLength(2);
});

it("blocks registration when no prepared endpoint is available and explains server preparation", async () => {
  const server = mockServer(undefined, { ...options, endpoints: [], secret_references: [] }); panel();
  fireEvent.click(screen.getByLabelText("새 연결 등록"));
  expect(await screen.findByText(/AI_WORKSHOP_PROVIDER_ENDPOINT_REFS/)).toBeVisible();
  expect(screen.getByText(/docs\/runbooks\/local-development.md/)).toBeVisible();
  expect(screen.getByRole("button", { name: "모델 연결 등록" })).toBeDisabled();
  submit(); expect(server.writes).toEqual([]);
});

it("requires explicit capabilities and a typed model identifier before any write", async () => {
  const server = mockServer(); panel(); await fillNew();
  fireEvent.click(screen.getByLabelText(/구조화된 출력/)); submit();
  expect(await screen.findByRole("alert")).toHaveTextContent(/지원 기능/);
  expect(server.writes).toEqual([]);
  fireEvent.click(screen.getByLabelText(/구조화된 출력/));
  fireEvent.change(screen.getByLabelText("공급자 모델 ID"), { target: { value: "" } }); submit();
  expect(screen.getByRole("alert")).toHaveTextContent(/모델 ID/); expect(server.writes).toEqual([]);
});

it("clears provider-specific references when the provider changes", async () => {
  const server = mockServer(); panel(); await fillNew("openai");
  fireEvent.click(screen.getByLabelText("로컬·사내"));
  expect(screen.getByLabelText("서버 연결")).toHaveValue("");
  expect(screen.getByLabelText(/구조화된 출력/)).not.toBeChecked();
  fireEvent.click(screen.getByLabelText("OpenAI"));
  expect(screen.getByLabelText("서버 인증")).toHaveValue("");
  submit(); expect(server.writes).toEqual([]);
});

it("requires reselecting an existing model definition after changing the provider", async () => {
  mockServer(); panel(); await fillNew();
  fireEvent.change(screen.getByLabelText("모델 정의"), { target: { value: "llm-id" } });
  fireEvent.click(screen.getByLabelText("OpenAI"));
  expect(screen.getByLabelText("모델 정의")).toHaveValue("");
});

it.each([
  ["model", "network"], ["deployment", "network"],
  ["model", "server"], ["deployment", "server"],
])("blocks duplicate registration after an uncertain %s %s response", async (stage, failure) => {
  const server = mockServer(write => {
    if (stage === "model" || write.path.endsWith("/deployments")) {
      if (failure === "server") return json({ error: { code: "internal_error", message: "sensitive network detail", correlation_id: "test" } }, 500);
      throw new TypeError("sensitive network detail");
    }
    return json(createdModel);
  });
  const callbacks = panel(); await fillNew(); submit();
  expect(await screen.findByRole("alert")).toHaveTextContent(/등록 결과를 확인하지 못/);
  const count = stage === "model" ? 1 : 2;
  expect(server.writes).toHaveLength(count);
  submit(); expect(server.writes).toHaveLength(count);
  expect(screen.getByRole("button", { name: /등록 결과 확인 필요/ })).toBeDisabled();
  expect(screen.queryByText(/sensitive network detail/)).not.toBeInTheDocument();
  expect(callbacks.onDeploymentSaved).not.toHaveBeenCalled();
  fireEvent.click(screen.getByLabelText("기존 연결 선택"));
  expect(screen.getByLabelText("기존 모델 연결")).toBeEnabled();
});

it("reports option authorization failure safely and keeps existing selection available", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({ error: { code: "owner_required", message: "sensitive", correlation_id: "test" } }, 403)));
  const callbacks = panel();
  expect(await screen.findByRole("alert")).toHaveTextContent(/소유자 권한/);
  expect(screen.queryByText("sensitive")).not.toBeInTheDocument();
  fireEvent.change(screen.getByLabelText("기존 모델 연결"), { target: { value: "version-id" } });
  expect(callbacks.onSelectDeployment).toHaveBeenCalledWith("version-id");
});

it("shows a dated public catalog newest first without requiring a key or selecting a model", async () => {
  const server = mockServer(undefined, { ...options, secret_references: [] }); panel();
  fireEvent.click(screen.getByLabelText("새 연결 등록"));
  await screen.findByRole("option", { name: /local-server/ });
  fireEvent.click(screen.getByLabelText("OpenAI"));
  const select = screen.getByRole("combobox", { name: "OpenAI 모델" });
  expect(select).toHaveValue("");
  expect(within(select).getAllByRole("option").map(option => (option as HTMLOptionElement).value)).toEqual([
    "", "gpt-6.1-terra", "gpt-6.1-sol", "gpt-6-luna", "gpt-6-sol", "gpt-6-astra",
  ]);
  expect(screen.getByText("2026-10-30").closest("p")).toHaveTextContent(/확인일.*2026-10-30/);
  expect(screen.getByText("2026-10-30")).toBeVisible();
  expect(screen.getByText(/주요 공개.*모델/)).toBeVisible();
  expect(screen.getByText(/계정별 사용 가능 여부.*연결/)).toBeVisible();
  expect(screen.getByText(/공식 API 지원.*이 앱/)).toBeVisible();
  expect(screen.getByLabelText(/구조화된 출력/)).not.toBeChecked();
  expect(screen.queryByRole("textbox", { name: "공급자 모델 ID" })).not.toBeInTheDocument();
  expect(server.fetcher).toHaveBeenCalledTimes(1); expect(server.writes).toEqual([]);
});

it("requires a catalog selection and rejects an unlisted injected selection before saving", async () => {
  const server = mockServer(); panel(); await fillNew("openai");
  const select = screen.getByLabelText("OpenAI 모델");
  fireEvent.change(select, { target: { value: "" } }); submit();
  expect(screen.getByRole("alert")).toHaveTextContent(/모델/); expect(server.writes).toEqual([]);
  const injected = document.createElement("option"); injected.value = "unlisted-provider-model"; select.appendChild(injected);
  fireEvent.change(select, { target: { value: "unlisted-provider-model" } });
  fireEvent.click(screen.getByLabelText(/구조화된 출력/)); submit();
  expect(screen.getByRole("alert")).toHaveTextContent(/목록.*선택/); expect(server.writes).toEqual([]);
});

it("clears the previous model and capability confirmation when switching input method or provider", async () => {
  const server = mockServer(); panel(); await fillNew("openai");
  fireEvent.click(screen.getByLabelText("직접 입력 · 고급"));
  expect(screen.getByLabelText("공급자 모델 ID")).toHaveValue("");
  expect(screen.getByLabelText(/구조화된 출력/)).not.toBeChecked();
  fireEvent.change(screen.getByLabelText("공급자 모델 ID"), { target: { value: "custom-approved-model" } });
  fireEvent.click(screen.getByLabelText(/구조화된 출력/));
  fireEvent.click(screen.getByLabelText("주요 모델 목록"));
  expect(screen.getByLabelText("OpenAI 모델")).toHaveValue("");
  expect(screen.getByLabelText(/구조화된 출력/)).not.toBeChecked();
  fireEvent.change(screen.getByLabelText("OpenAI 모델"), { target: { value: "gpt-6.1-sol" } });
  fireEvent.click(screen.getByLabelText("로컬·사내"));
  expect(screen.getByLabelText("공급자 모델 ID")).toHaveValue("");
  fireEvent.change(screen.getByLabelText("공급자 모델 ID"), { target: { value: "local-installed-model" } });
  fireEvent.click(screen.getByLabelText("OpenAI"));
  expect(screen.getByLabelText("OpenAI 모델")).toHaveValue(""); expect(server.writes).toEqual([]);
});

it("requires new capability confirmation after changing the selected or manually entered model", async () => {
  const server = mockServer(); panel(); await fillNew("openai");
  fireEvent.change(screen.getByLabelText("OpenAI 모델"), { target: { value: "gpt-6.1-sol" } });
  expect(screen.getByLabelText(/구조화된 출력/)).not.toBeChecked();
  submit(); expect(screen.getByRole("alert")).toHaveTextContent(/지원 기능/); expect(server.writes).toEqual([]);
  fireEvent.click(screen.getByLabelText("직접 입력 · 고급"));
  fireEvent.change(screen.getByLabelText("공급자 모델 ID"), { target: { value: "custom-model-a" } });
  fireEvent.click(screen.getByLabelText(/구조화된 출력/));
  fireEvent.change(screen.getByLabelText("공급자 모델 ID"), { target: { value: "custom-model-b" } });
  expect(screen.getByLabelText(/구조화된 출력/)).not.toBeChecked();
});

it("preserves explicit manual OpenAI registration without substituting a catalog model", async () => {
  const server = mockServer(); const callbacks = panel(); await fillNew("openai");
  fireEvent.click(screen.getByLabelText("직접 입력 · 고급"));
  fireEvent.change(screen.getByLabelText("공급자 모델 ID"), { target: { value: "  custom-approved-model  " } });
  fireEvent.click(screen.getByLabelText(/구조화된 출력/)); submit();
  await waitFor(() => expect(callbacks.onDeploymentSaved).toHaveBeenCalled());
  expect(server.writes[0].body.config).toEqual({ model_identifier: "custom-approved-model" });
  expect(server.writes[1].body.provider_model_id).toBe("custom-approved-model");
});

it("keeps catalog selection and input mode locked after partial model success", async () => {
  const server = mockServer((write, count) => count === 2 ? json({ error: { code: "unknown_endpoint_reference", message: "rejected", correlation_id: "test" } }, 422) : json(write.path.endsWith("/models") ? createdModel : savedDeployment));
  panel(); await fillNew("openai"); submit(); await screen.findByRole("alert");
  expect(screen.getByLabelText("OpenAI 모델")).toHaveValue("gpt-6.1-terra");
  expect(screen.getByLabelText("OpenAI 모델")).toBeDisabled();
  expect(screen.getByLabelText("직접 입력 · 고급")).toBeDisabled();
  submit(); await waitFor(() => expect(server.writes).toHaveLength(3));
  expect(server.writes[2].body.provider_model_id).toBe("gpt-6.1-terra");
});

it("shows verified parameter limits without claiming the model is accepted by this app", async () => {
  mockServer(); panel(); await fillNew("openai");
  fireEvent.change(screen.getByLabelText("OpenAI 모델"), { target: { value: "gpt-6-astra" } });
  expect(screen.getByText(/사용자 지정 temperature.*지원하지/)).toBeVisible();
  expect(screen.getByRole("link", { name: "선택한 모델 공식 문서" })).toHaveAttribute("href", "https://developers.openai.com/api/docs/models/gpt-6-astra");
  expect(screen.getByLabelText(/구조화된 출력/)).not.toBeChecked();
});
