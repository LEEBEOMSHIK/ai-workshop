import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string).config.generation.response_schema_version).toBe(1);
});

it("uses explicit provider default sampling and schema 1 for Claude without SDK", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json(saved)); vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[{ ...deployment, provider: "anthropic_messages", location: "external", external_transfer: true }]} onSaved={() => {}} />);
  fireEvent.change(screen.getByLabelText("HTTP 생성 프로파일 이름"), { target: { value: "Claude candidate" } });
  expect(screen.getByLabelText("OpenAI Agents SDK")).toBeDisabled();
  expect(screen.getByText(/공급자 기본 생성 설정/)).toBeVisible();
  submit();
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  const config = JSON.parse(fetcher.mock.calls[0][1]!.body as string).config;
  expect(config).toMatchObject({prompt_ref:"rag-answer-v1", context_prompt_ref:"rag-contextualize-v1",
    generation: {response_schema_version:1, temperature:1, sampling_mode:"provider_default"}});
  expect(config.orchestration).toBeUndefined();
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

it("opts into SDK orchestration with explicit limits while registering only a draft", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json(saved)); vi.stubGlobal("fetch", fetcher);
  const onSaved = vi.fn();
  render(<HttpGenerationForm deployments={[deployment]} onSaved={onSaved} />);
  expect(screen.getByRole("radio", { name: "직접 실행" })).toBeChecked();
  fill();
  await userEvent.click(screen.getByRole("radio", { name: "OpenAI Agents SDK" }));
  expect(screen.getByLabelText("전체 모델 호출 한도")).toHaveValue("3");
  expect(screen.getByLabelText("전체 출력 예약 한도 (토큰)")).toHaveValue(3072);
  expect(screen.getByText(/첫 질문.*2회/)).toBeVisible();
  expect(screen.getByText(/후속 질문.*최대 3회/)).toBeVisible();
  expect(screen.getByText(/누적 LLM 시간/)).toBeVisible();
  expect(screen.getByText(/재시도 0회/)).toBeVisible();
  submit();
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toMatchObject({
    deployment_version_id: "http-version", evaluation_state: "draft",
    config: {
      generation: { max_output_tokens: 1024, response_schema_version: 2 },
      orchestration: { engine: "openai_agents", version: 1, max_model_calls: 3, max_tool_calls: 1, max_total_output_tokens: 3072 },
    },
  });
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string).config.orchestration).toEqual({
    engine: "openai_agents", version: 1, max_model_calls: 3, max_tool_calls: 1, max_total_output_tokens: 3072,
  });
});

it("explicitly registers autonomous handoffs with bounded calls as a draft without inference or promotion", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json(saved)); vi.stubGlobal("fetch", fetcher);
  const onSaved = vi.fn();
  render(<HttpGenerationForm deployments={[deployment]} onSaved={onSaved} />);
  fill();
  await userEvent.click(screen.getByRole("radio", { name: "OpenAI Agents SDK" }));
  expect(screen.getByRole("radio", { name: "관리자 위임" })).toBeChecked();
  await userEvent.click(screen.getByRole("radio", { name: "자율 재위임" }));
  expect(screen.getByLabelText("전체 모델 호출 한도")).toHaveValue(3);
  expect(screen.getByLabelText("전체 재위임 한도")).toHaveValue(2);
  expect(screen.getByLabelText("전체 출력 예약 한도 (토큰)")).toHaveValue(3072);
  expect(screen.getByText(/근거 담당.*답변 담당.*최소.*2회/)).toBeVisible();
  expect(screen.getByText(/문맥화.*1회.*더/)).toBeVisible();
  expect(screen.getByText(/추가 재위임.*예산/)).toBeVisible();
  expect(screen.getByText(/선택된 원문 근거만.*추가 검색/)).toBeVisible();
  expect(screen.getByText(/최종 답변.*인용 검증/)).toBeVisible();
  expect(fetcher).not.toHaveBeenCalled();
  submit();
  await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe("/api/v1/admin/rag/profiles/generation");
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toEqual({
    name: "Synthetic generation", version: 1, deployment_version_id: "http-version", bindings: [], evaluation_state: "draft",
    config: { prompt_ref: "synthetic-answer", context_prompt_ref: "synthetic-context", citation_mode: "required",
      context_policy: { max_history_turns: 4, max_history_tokens: 1024 },
      generation: { timeout_seconds: 60, max_output_tokens: 1024, temperature: 0, response_schema_version: 2 },
      orchestration: { engine: "openai_agents", version: 2, dispatch_mode: "autonomous_handoffs",
        max_model_calls: 3, max_tool_calls: 2, max_total_output_tokens: 3072 } },
  });
});

it.each([
  ["전체 모델 호출 한도", ""], ["전체 모델 호출 한도", "1"], ["전체 모델 호출 한도", "9"],
  ["전체 모델 호출 한도", "2.5"], ["전체 재위임 한도", ""], ["전체 재위임 한도", "0"],
  ["전체 재위임 한도", "8"], ["전체 재위임 한도", "1.5"],
  ["전체 출력 예약 한도 (토큰)", "3071"], ["전체 출력 예약 한도 (토큰)", "2147483648"],
])("rejects autonomous budget %s=%s without a request", (label, value) => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[deployment]} onSaved={() => {}} />);
  fill();
  fireEvent.click(screen.getByRole("radio", { name: "OpenAI Agents SDK" }));
  fireEvent.click(screen.getByRole("radio", { name: "자율 재위임" }));
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
  submit();
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("에이전트");
});

it.each([[2, 1], [8, 7]])("accepts the explicit autonomous bounds of %s model calls and %s handoffs", async (modelCalls, handoffs) => {
  const fetcher = vi.fn<typeof fetch>(async () => json(saved)); vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[deployment]} onSaved={() => {}} />);
  fill();
  fireEvent.click(screen.getByRole("radio", { name: "OpenAI Agents SDK" }));
  fireEvent.click(screen.getByRole("radio", { name: "자율 재위임" }));
  fireEvent.change(screen.getByLabelText("전체 모델 호출 한도"), { target: { value: String(modelCalls) } });
  fireEvent.change(screen.getByLabelText("전체 재위임 한도"), { target: { value: String(handoffs) } });
  fireEvent.change(screen.getByLabelText("전체 출력 예약 한도 (토큰)"), { target: { value: "8192" } });
  submit();
  await waitFor(() => expect(screen.getByRole("status")).toBeVisible());
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string).config.orchestration).toEqual({
    engine: "openai_agents", version: 2, dispatch_mode: "autonomous_handoffs",
    max_model_calls: modelCalls, max_tool_calls: handoffs, max_total_output_tokens: 8192,
  });
});

it("keeps each SDK mode's entered budgets across keyboard routing and direct mode changes", async () => {
  const user = userEvent.setup();
  const fetcher = vi.fn<typeof fetch>(async () => json(saved)); vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[deployment]} onSaved={() => {}} />);
  fill();
  await user.click(screen.getByRole("radio", { name: "OpenAI Agents SDK" }));
  fireEvent.change(screen.getByLabelText("전체 모델 호출 한도"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("전체 출력 예약 한도 (토큰)"), { target: { value: "5000" } });
  screen.getByRole("radio", { name: "관리자 위임" }).focus();
  await user.keyboard("{ArrowRight}");
  expect(screen.getByRole("radio", { name: "자율 재위임" })).toBeChecked();
  expect(screen.getByRole("radio", { name: "자율 재위임" })).toHaveFocus();
  fireEvent.change(screen.getByLabelText("전체 모델 호출 한도"), { target: { value: "4" } });
  fireEvent.change(screen.getByLabelText("전체 재위임 한도"), { target: { value: "3" } });
  fireEvent.change(screen.getByLabelText("전체 출력 예약 한도 (토큰)"), { target: { value: "7000" } });
  await user.keyboard("{ArrowLeft}");
  expect(screen.getByRole("radio", { name: "관리자 위임" })).toBeChecked();
  expect(screen.getByLabelText("전체 모델 호출 한도")).toHaveValue("2");
  expect(screen.getByLabelText("전체 출력 예약 한도 (토큰)")).toHaveValue(5000);
  expect(screen.queryByLabelText("전체 재위임 한도")).not.toBeInTheDocument();
  submit();
  await waitFor(() => expect(screen.getByRole("status")).toBeVisible());
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string).config.orchestration).toEqual({
    engine: "openai_agents", version: 1, max_model_calls: 2, max_tool_calls: 1, max_total_output_tokens: 5000,
  });
  await user.click(screen.getByRole("radio", { name: "자율 재위임" }));
  expect(screen.getByLabelText("전체 모델 호출 한도")).toHaveValue(4);
  expect(screen.getByLabelText("전체 재위임 한도")).toHaveValue(3);
  expect(screen.getByLabelText("전체 출력 예약 한도 (토큰)")).toHaveValue(7000);
  await user.click(screen.getByRole("radio", { name: "직접 실행" }));
  expect(screen.queryByRole("radio", { name: "자율 재위임" })).not.toBeInTheDocument();
  await user.click(screen.getByRole("radio", { name: "OpenAI Agents SDK" }));
  expect(screen.getByRole("radio", { name: "자율 재위임" })).toBeChecked();
  expect(screen.getByLabelText("전체 모델 호출 한도")).toHaveValue(4);
  expect(screen.getByLabelText("전체 재위임 한도")).toHaveValue(3);
  expect(screen.getByLabelText("전체 출력 예약 한도 (토큰)")).toHaveValue(7000);
});

it("preserves SDK inputs across modes and submits only the chosen mode's configuration", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json(saved)); vi.stubGlobal("fetch", fetcher);
  const onSaved = vi.fn();
  render(<HttpGenerationForm deployments={[deployment]} onSaved={onSaved} />);
  fill();
  await userEvent.click(screen.getByRole("radio", { name: "OpenAI Agents SDK" }));
  fireEvent.change(screen.getByLabelText("전체 모델 호출 한도"), { target: { value: "2" } });
  fireEvent.change(screen.getByLabelText("전체 출력 예약 한도 (토큰)"), { target: { value: "5000" } });
  fireEvent.change(screen.getByLabelText("최대 출력 토큰"), { target: { value: "2048" } });
  expect(screen.getByText(/현재 설정의 출력 예약 합계: 4096 토큰/)).toBeVisible();
  await userEvent.click(screen.getByRole("radio", { name: "직접 실행" }));
  expect(screen.queryByLabelText("전체 출력 예약 한도 (토큰)")).not.toBeInTheDocument();
  submit();
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
  const direct = JSON.parse(fetcher.mock.calls[0][1]!.body as string);
  expect(direct.config).not.toHaveProperty("orchestration");
  expect(direct.config.generation.max_output_tokens).toBe(2048);
  await userEvent.click(screen.getByRole("radio", { name: "OpenAI Agents SDK" }));
  expect(screen.getByLabelText("전체 모델 호출 한도")).toHaveValue("2");
  expect(screen.getByLabelText("전체 출력 예약 한도 (토큰)")).toHaveValue(5000);
  submit();
  await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(2));
  expect(JSON.parse(fetcher.mock.calls[1][1]!.body as string).config.orchestration).toEqual({
    engine: "openai_agents", version: 1, max_model_calls: 2, max_tool_calls: 1, max_total_output_tokens: 5000,
  });
});

it.each([
  ["전체 모델 호출 한도", "1"], ["전체 모델 호출 한도", "4"],
  ["전체 출력 예약 한도 (토큰)", ""], ["전체 출력 예약 한도 (토큰)", "0"],
  ["전체 출력 예약 한도 (토큰)", "1.5"], ["전체 출력 예약 한도 (토큰)", "2147483648"],
  ["전체 출력 예약 한도 (토큰)", "2048"],
])("rejects invalid SDK budget %s=%s without making a request", (label, value) => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[deployment]} onSaved={() => {}} />);
  fill();
  fireEvent.click(screen.getByRole("radio", { name: "OpenAI Agents SDK" }));
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
  submit();
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent("에이전트");
});

it("does not validate hidden SDK limits when the user explicitly chooses direct execution", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json(saved)); vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[deployment]} onSaved={() => {}} />);
  fill();
  fireEvent.click(screen.getByRole("radio", { name: "OpenAI Agents SDK" }));
  fireEvent.change(screen.getByLabelText("전체 출력 예약 한도 (토큰)"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("radio", { name: "직접 실행" }));
  submit();
  await waitFor(() => expect(screen.getByRole("status")).toBeVisible());
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string).config).not.toHaveProperty("orchestration");
  fireEvent.click(screen.getByRole("radio", { name: "OpenAI Agents SDK" }));
  expect(screen.getByLabelText("전체 출력 예약 한도 (토큰)")).toHaveValue(null);
});

it.each([
  { provider: "openai_responses" as const },
  { location: "on_premise" as const },
  { external_transfer: true },
])("disables SDK for unsupported deployment settings %j", async (unsupported) => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  render(<HttpGenerationForm deployments={[{ ...deployment, ...unsupported }]} onSaved={() => {}} />);
  const sdk = screen.getByRole("radio", { name: "OpenAI Agents SDK" });
  expect(sdk).toBeDisabled();
  await userEvent.click(sdk);
  expect(screen.getByRole("radio", { name: "직접 실행" })).toBeChecked();
  expect(screen.getByText(/선택한 배포에서는 SDK 실행을 지원하지 않습니다/)).toBeVisible();
  expect(fetcher).not.toHaveBeenCalled();
});

it("blocks an unsupported deployment after opt-in without silently changing the execution mode", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json(saved)); vi.stubGlobal("fetch", fetcher);
  const unsupported = { ...deployment, version_id: "unsupported", provider: "openai_responses" as const };
  render(<HttpGenerationForm deployments={[deployment, unsupported]} onSaved={() => {}} />);
  fill();
  await userEvent.click(screen.getByRole("radio", { name: "OpenAI Agents SDK" }));
  fireEvent.change(screen.getByLabelText("전체 출력 예약 한도 (토큰)"), { target: { value: "5000" } });
  fireEvent.change(screen.getByLabelText("HTTP 배포 버전"), { target: { value: "unsupported" } });
  expect(screen.getByRole("radio", { name: "OpenAI Agents SDK" })).toBeChecked();
  expect(screen.getByRole("button", { name: "HTTP 생성 프로파일 등록" })).toBeDisabled();
  submit();
  expect(fetcher).not.toHaveBeenCalled();
  expect(screen.getByRole("alert")).toHaveTextContent(/SDK 실행을 지원하지 않습니다/);
  fireEvent.change(screen.getByLabelText("HTTP 배포 버전"), { target: { value: "http-version" } });
  expect(screen.getByLabelText("전체 출력 예약 한도 (토큰)")).toHaveValue(5000);
  expect(screen.getByRole("button", { name: "HTTP 생성 프로파일 등록" })).toBeEnabled();
  fireEvent.change(screen.getByLabelText("HTTP 배포 버전"), { target: { value: "unsupported" } });
  await userEvent.click(screen.getByRole("radio", { name: "직접 실행" }));
  submit();
  await waitFor(() => expect(screen.getByRole("status")).toBeVisible());
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toMatchObject({ deployment_version_id: "unsupported" });
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string).config).not.toHaveProperty("orchestration");
});
