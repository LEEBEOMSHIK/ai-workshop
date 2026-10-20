import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { HttpGenerationForm } from "./HttpGenerationForm";
import type { DeploymentSummary, ProfileSummary } from "./api";

const deployment: DeploymentSummary = {
  deployment_id: "deployment", version_id: "http-version", version: 2,
  display_name: "Synthetic HTTP", description: "", model_name: "Synthetic model", model_version: 1,
  provider: "local_openai_compatible", provider_model_id: "synthetic-model", runner_ref: null,
  location: "local", external_transfer: false, allowed_environments: ["development"],
  capabilities: ["structured_output"], secret_configured: false,
  readiness: { ready: false, reason_codes: ["deployment_not_ready"] }, latest_health: null,
};
const saved: ProfileSummary = {
  id: "profile", kind: "generation", name: "Synthetic generation", version: 1,
  config: {}, bindings: [], deployment_version_id: "http-version", evaluation_state: "draft",
  is_default: false, legacy: false, readiness: { ready: false, reason_codes: ["deployment_not_ready"] },
};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "content-type": "application/json" },
});
afterEach(() => vi.unstubAllGlobals());
function fill() {
  fireEvent.change(screen.getByLabelText("HTTP 생성 프로파일 이름"), { target: { value: " Synthetic generation " } });
  fireEvent.change(screen.getByLabelText("답변 지침 참조"), { target: { value: " synthetic-answer " } });
  fireEvent.change(screen.getByLabelText("문맥화 지침 참조"), { target: { value: "synthetic-context" } });
}
function submit() {
  fireEvent.submit(screen.getByRole("heading", { name: "HTTP 생성 프로파일" }).closest("form")!);
}

it("registers an exact HTTP deployment with explicit settings and no promotion or inference", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json(saved)); vi.stubGlobal("fetch", fetcher);
  const onSaved = vi.fn();
  render(<HttpGenerationForm deployments={[deployment, { ...deployment, version_id: "second", version: 3 }]} onSaved={onSaved} />);
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByLabelText("답변 지침 참조")).toHaveValue("");
  fill();
  fireEvent.change(screen.getByLabelText("HTTP 배포 버전"), { target: { value: "second" } });
  fireEvent.change(screen.getByLabelText("HTTP 생성 프로파일 버전"), { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText("시간 제한 (초)"), { target: { value: "90" } });
  fireEvent.change(screen.getByLabelText("최대 출력 토큰"), { target: { value: "2048" } });
  fireEvent.change(screen.getByLabelText("이력 턴 한도"), { target: { value: "6" } });
  fireEvent.change(screen.getByLabelText("이력 토큰 한도"), { target: { value: "2000" } });
  fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "0.2" } });
  submit();
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe("/api/v1/admin/rag/profiles/generation");
  expect(fetcher.mock.calls[0][1]).toMatchObject({ method: "POST", credentials: "include" });
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toEqual({
    name: "Synthetic generation", version: 4, deployment_version_id: "second", bindings: [], evaluation_state: "draft",
    config: { prompt_ref: "synthetic-answer", context_prompt_ref: "synthetic-context", citation_mode: "required",
      context_policy: { max_history_turns: 6, max_history_tokens: 2000 },
      generation: { timeout_seconds: 90, max_output_tokens: 2048, temperature: 0.2, response_schema_version: 2 } },
  });
  expect(screen.getByRole("status")).toHaveTextContent("구성 스튜디오");
});

it.each(["development_codex_exec", "local_transformers"] as const)("does not accept the %s provider", (provider) => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[{ ...deployment, provider }]} onSaved={() => {}} />);
  expect(screen.getByText(/등록된 HTTP 배포가 없습니다/)).toBeVisible();
  expect(screen.getByRole("button", { name: "HTTP 생성 프로파일 등록" })).toBeDisabled();
  submit(); expect(fetcher).not.toHaveBeenCalled();
});

it.each([
  ["HTTP 생성 프로파일 이름", "   "], ["답변 지침 참조", "   "], ["문맥화 지침 참조", ""],
  ["HTTP 생성 프로파일 버전", "1.5"], ["시간 제한 (초)", "0"], ["최대 출력 토큰", "1.5"],
  ["이력 턴 한도", "0"], ["이력 토큰 한도", "1.5"], ["Temperature", "2.1"], ["Temperature", ""],
])("rejects invalid %s input %s without a request", (label, value) => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[deployment]} onSaved={() => {}} />);
  fill(); fireEvent.change(screen.getByLabelText(label), { target: { value } }); submit();
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("입력");
});

it.each([403, 409, 422, 503])("preserves inputs and shows safe server errors for HTTP %s", async (status) => {
  const fetcher = vi.fn<typeof fetch>(async () => json({ error: { code: "safe_error", message: "private raw detail", correlation_id: "synthetic-id" } }, status));
  vi.stubGlobal("fetch", fetcher); const onSaved = vi.fn();
  render(<HttpGenerationForm deployments={[deployment]} onSaved={onSaved} />);
  fill(); submit();
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("safe_error"));
  expect(screen.getByRole("alert")).not.toHaveTextContent("private raw detail");
  expect(screen.getByLabelText("HTTP 생성 프로파일 이름")).toHaveValue(" Synthetic generation ");
  expect(screen.getByLabelText("답변 지침 참조")).toHaveValue(" synthetic-answer ");
  expect(onSaved).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "HTTP 생성 프로파일 등록" })).toBeEnabled();
});

it("blocks duplicate submissions while keeping the exact original request", async () => {
  let complete!: (value: Response) => void;
  const pending = new Promise<Response>((resolve) => { complete = resolve; });
  const fetcher = vi.fn<typeof fetch>(() => pending); vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[deployment]} onSaved={() => {}} />);
  fill(); submit(); submit();
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "등록 중…" })).toBeDisabled();
  complete(json(saved));
  await waitFor(() => expect(screen.getByRole("button", { name: "HTTP 생성 프로파일 등록" })).toBeEnabled());
});

it("requires an explicit replacement when the selected deployment disappears", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const onSaved = vi.fn();
  const other = { ...deployment, version_id: "other" };
  const view = render(<HttpGenerationForm deployments={[deployment, other]} onSaved={onSaved} />);
  fill(); fireEvent.change(screen.getByLabelText("HTTP 배포 버전"), { target: { value: "other" } });
  view.rerender(<HttpGenerationForm deployments={[deployment]} onSaved={onSaved} />);
  submit(); expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByRole("button", { name: "HTTP 생성 프로파일 등록" })).toBeDisabled();
  expect(screen.getByLabelText("HTTP 배포 버전")).toBeEnabled();
  fireEvent.change(screen.getByLabelText("HTTP 배포 버전"), { target: { value: deployment.version_id } });
  expect(screen.getByRole("button", { name: "HTTP 생성 프로파일 등록" })).toBeEnabled();
});

it("supports an existing OpenAI HTTP deployment without Codex headers", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json(saved)); vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[{ ...deployment, provider: "openai_responses" }]} onSaved={() => {}} />);
  fill(); submit();
  await waitFor(() => expect(screen.getByRole("status")).toBeVisible());
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(new Headers(fetcher.mock.calls[0][1]?.headers).has("x-codex-request")).toBe(false);
});

it("allows retry after a network failure without showing raw exception details", async () => {
  const fetcher = vi.fn<typeof fetch>().mockRejectedValueOnce(new Error("private network detail")).mockResolvedValueOnce(json(saved));
  vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[deployment]} onSaved={() => {}} />);
  fill(); submit();
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("요청을 완료하지 못했습니다"));
  expect(screen.queryByText(/private network detail/)).not.toBeInTheDocument();
  submit(); await waitFor(() => expect(screen.getByRole("status")).toBeVisible());
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("saves explicit contextual evidence limits for the supported schema 2 answer prompt", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json(saved)); vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[deployment]} onSaved={() => {}} />);
  fill();
  fireEvent.change(screen.getByLabelText("답변 지침 참조"), { target: { value: "rag-answer-v2" } });
  fireEvent.click(screen.getByLabelText("문맥 근거 한도 지정"));
  fireEvent.change(screen.getByLabelText("근거 그룹 한도"), { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText("근거 단위 한도"), { target: { value: "16" } });
  fireEvent.change(screen.getByLabelText("근거 문자 수 한도"), { target: { value: "8000" } });
  submit(); await waitFor(() => expect(screen.getByRole("status")).toBeVisible());
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string).config).toMatchObject({
    prompt_ref: "rag-answer-v2", generation: { response_schema_version: 2 },
    context_evidence: { version: 1, max_groups: 4, max_units: 16, max_characters: 8000 },
  });
});

it.each([
  ["근거 그룹 한도", "0"], ["근거 그룹 한도", "33"],
  ["근거 단위 한도", "1.5"], ["근거 문자 수 한도", ""],
])("rejects invalid evidence limits %s=%s", (label, value) => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[deployment]} onSaved={() => {}} />);
  fill(); fireEvent.click(screen.getByLabelText("문맥 근거 한도 지정"));
  fireEvent.change(screen.getByLabelText(label), { target: { value } }); submit();
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("근거");
});
