import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";
import { CodexVerificationPanel } from "./CodexVerificationPanel";
afterEach(() => vi.unstubAllGlobals());

it("keeps consent while passively querying an unverified status", async () => {
  const user = userEvent.setup();
  let finishRequest!: (response: Response) => void;
  const fetch = vi.fn(() => new Promise<Response>((resolve) => { finishRequest = resolve; }));
  vi.stubGlobal("fetch", fetch);
  render(<CodexVerificationPanel versionId="exact-version" disclosure="OpenAI 외부 처리" disclosureVersion="v1" />);
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "저장된 검사 상태 조회" }));
  expect(screen.getByRole("status")).toHaveTextContent(/조회 중/);
  expect(screen.getByRole("checkbox")).toBeChecked();
  finishRequest(new Response(JSON.stringify({ ready: false, safe_error_code: "codex_verification_required", requested_provider_model_id: "requested-model", observed_provider_model_id: null, model_identity_status: "unknown", checked_at: null }), { headers: { "content-type": "application/json" } }));
  expect(await screen.findByText(/연결 검사 필요/)).toBeVisible();
  expect(screen.getByRole("checkbox")).toBeChecked();
  expect(screen.getByRole("button", { name: "합성 입력으로 연결 검사" })).toBeEnabled();
  expect(fetch).toHaveBeenCalledTimes(1);
});

it.each(["network rejection", "unstructured HTTP error"])("recovers an unknown POST outcome (%s) through explicit saved status lookup without retrying POST", async (failure) => {
  const user = userEvent.setup();
  const fetch = vi.fn();
  if (failure === "network rejection") fetch.mockRejectedValueOnce(new TypeError("Failed to fetch"));
  else fetch.mockResolvedValueOnce(new Response("Gateway timeout", { status: 504 }));
  fetch.mockResolvedValueOnce(new Response(JSON.stringify({ ready: true, safe_error_code: null, requested_provider_model_id: "requested-model", observed_provider_model_id: null, model_identity_status: "unknown", checked_at: "2026-09-10T01:23:45Z" }), { headers: { "content-type": "application/json" } }));
  vi.stubGlobal("fetch", fetch);
  render(<CodexVerificationPanel versionId="exact-version" disclosure="OpenAI 외부 처리" disclosureVersion="v1" />);
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "합성 입력으로 연결 검사" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/실행 결과를 확인할 수 없습니다/);
  expect(screen.getByRole("alert")).toHaveTextContent(/저장된 검사 상태 조회/);
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(fetch).toHaveBeenCalledTimes(1);
  await user.click(screen.getByRole("button", { name: "저장된 검사 상태 조회" }));
  expect(await screen.findByText(/연결 검사 통과/)).toBeVisible();
  expect(screen.getByText(/검사 시각/)).toHaveTextContent("2026-09-10T01:23:45Z");
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[1][0]).toContain("/exact-version/codex-status");
});

it("labels retained success as previous after a lookup failure and restores it after a successful lookup", async () => {
  const user = userEvent.setup();
  const response = { ready: true, safe_error_code: null, requested_provider_model_id: "requested-model", observed_provider_model_id: "observed-model", model_identity_status: "verified", checked_at: "2026-09-09" };
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(response)))
    .mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockResolvedValueOnce(new Response(JSON.stringify(response)));
  vi.stubGlobal("fetch", fetch);
  render(<CodexVerificationPanel versionId="exact-version" disclosure="OpenAI 외부 처리" disclosureVersion="v1" />);
  await user.click(screen.getByRole("button", { name: "저장된 검사 상태 조회" }));
  expect(await screen.findByText(/연결 검사 통과/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "다시 검사" }));
  await user.click(screen.getByRole("checkbox"));
  await user.click(screen.getByRole("button", { name: "저장된 검사 상태 조회" }));
  expect(await screen.findByRole("alert")).toBeVisible();
  expect(screen.getByText(/이전 검사 결과/)).toHaveTextContent(/통과/);
  expect(screen.getByText(/검사 시각/)).toHaveTextContent("2026-09-09");
  expect(screen.getByText("이전 검사 실제 모델: observed-model")).toBeVisible();
  expect(screen.getByRole("checkbox")).toBeChecked();
  await user.click(screen.getByRole("button", { name: "저장된 검사 상태 조회" }));
  expect(await screen.findByText(/연결 검사 통과/)).toBeVisible();
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByText(/이전 검사 결과/)).not.toBeInTheDocument();
  expect(screen.getByRole("checkbox")).toBeChecked();
  expect(fetch).toHaveBeenCalledTimes(3);
  expect(fetch.mock.calls.every(([path]) => String(path).endsWith("/codex-status"))).toBe(true);
});

it("explains why execution is disabled and enables it by clicking the full consent label", async () => {
  const user = userEvent.setup();
  const fetch = vi.fn();
  vi.stubGlobal("fetch", fetch);
  render(<CodexVerificationPanel versionId="exact-version" disclosure="OpenAI 외부 처리" disclosureVersion="codex-external-generation-v1" />);
  const execute = screen.getByRole("button", { name: "합성 입력으로 연결 검사" });
  expect(execute).toBeDisabled();
  expect(execute).toHaveAccessibleDescription(/동의/);
  await user.click(execute);
  expect(fetch).not.toHaveBeenCalled();
  await user.click(screen.getByText("고지와 이 구성 버전의 합성 입력 외부 전송·계정 사용량을 확인하고 연결 검사에 동의합니다."));
  expect(screen.getByRole("checkbox")).toBeChecked();
  expect(execute).toBeEnabled();
  expect(fetch).not.toHaveBeenCalled();
});

it("lets keyboard users toggle consent with Space before reaching execution", async () => {
  const user = userEvent.setup();
  vi.stubGlobal("fetch", vi.fn());
  render(<CodexVerificationPanel versionId="exact-version" disclosure="OpenAI 외부 처리" disclosureVersion="codex-external-generation-v1" />);
  const execute = screen.getByRole("button", { name: "합성 입력으로 연결 검사" });
  await user.tab();
  expect(screen.getByRole("checkbox")).toHaveFocus();
  await user.keyboard(" ");
  expect(screen.getByRole("checkbox")).toBeChecked();
  expect(execute).toBeEnabled();
  await user.tab();
  expect(execute).toHaveFocus();
  await user.tab({ shift: true });
  await user.keyboard(" ");
  expect(execute).toBeDisabled();
});

it("separates a pending request from the old result and requires renewed consent after failure", async () => {
  const user = userEvent.setup();
  let finishRequest!: (response: Response) => void;
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ ready: true, safe_error_code: null, requested_provider_model_id: "requested-model", observed_provider_model_id: null, model_identity_status: "unknown", checked_at: "2026-09-09" }), { headers: { "content-type": "application/json" } }))
    .mockImplementationOnce(() => new Promise<Response>((resolve) => { finishRequest = resolve; }));
  vi.stubGlobal("fetch", fetch);
  render(<CodexVerificationPanel versionId="exact-version" disclosure="OpenAI 외부 처리" disclosureVersion="codex-external-generation-v1" />);
  await user.click(screen.getByRole("button", { name: "저장된 검사 상태 조회" }));
  expect(await screen.findByText(/연결 검사 통과/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "다시 검사" }));
  await user.click(screen.getByRole("checkbox"));
  const execute = screen.getByRole("button", { name: "합성 입력으로 연결 검사" });
  await user.click(execute);
  expect(screen.getByRole("checkbox")).toBeDisabled();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(execute).toBeDisabled();
  expect(screen.getByRole("button", { name: "저장된 검사 상태 조회" })).toBeDisabled();
  expect(screen.getByText(/이전 검사 결과/)).toHaveTextContent(/통과/);
  expect(screen.getByRole("status")).toHaveTextContent(/실행 중/);
  await user.click(execute);
  expect(fetch).toHaveBeenCalledTimes(2);
  finishRequest(new Response(JSON.stringify({ error: { code: "codex_preflight_failed", correlation_id: "safe-id", message: "Synthetic failure" } }), { status: 503, headers: { "content-type": "application/json" } }));
  expect(await screen.findByRole("alert")).toHaveTextContent("codex_preflight_failed");
  expect(screen.getByText(/이전 검사 결과/)).toHaveTextContent(/통과/);
  expect(screen.getByRole("checkbox")).toBeEnabled();
  expect(execute).toBeDisabled();
  expect(execute).toHaveAccessibleDescription(/동의/);
});
it("requires explicit consent for the exact saved version and keeps unknown observation", async () => {
  const calls: { path: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (path: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ path: String(path), init });
    return new Response(JSON.stringify({ ready: true, safe_error_code: null, requested_provider_model_id: "requested-model", observed_provider_model_id: null, model_identity_status: "unknown", checked_at: "2026-09-09" }), { headers: { "content-type": "application/json" } });
  }));
  render(<CodexVerificationPanel versionId="exact-version" disclosure="OpenAI 외부 처리" disclosureVersion="codex-external-generation-v1" requestedModel="requested-model" />);
  expect(calls).toHaveLength(0);
  expect(screen.getByText("실제 모델: 미확인")).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: "합성 입력으로 연결 검사" }));
  expect(calls).toHaveLength(0);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "합성 입력으로 연결 검사" }));
  await waitFor(() => expect(calls).toHaveLength(1));
  expect(calls[0].path).toBe("/api/v1/admin/rag/configuration-versions/exact-version/codex-verify");
  expect(JSON.parse(String(calls[0].init?.body))).toEqual({ consented: true, disclosure_version: "codex-external-generation-v1" });
  expect(calls[0].init?.headers).toMatchObject({ "x-codex-request": "1", "content-type": "application/json" });
  expect(await screen.findByText(/연결 검사 통과/)).toBeVisible();
  expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  expect(screen.getByText(/검사 시각/)).toHaveTextContent("2026-09-09");
  fireEvent.click(screen.getByRole("button", { name: "다시 검사" }));
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  expect(screen.getByRole("button", { name: "합성 입력으로 연결 검사" })).toBeDisabled();
  expect(screen.getByText("실제 모델: 미확인")).toBeVisible();
});

it("reads passive status and shows safe failure metadata without raw provider messages", async () => {
  const calls: { path: string; method?: string }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (path: RequestInfo | URL, init?: RequestInit) => {
    calls.push({ path: String(path), method: init?.method });
    return new Response(JSON.stringify({ error: { code: "codex_preflight_failed", correlation_id: "safe-id", message: "DO_NOT_SHOW_PROVIDER_DETAIL" } }), { status: 503, headers: { "content-type": "application/json" } });
  }));
  render(<CodexVerificationPanel versionId="another-version" disclosure="OpenAI 외부 처리" disclosureVersion="codex-external-generation-v1" />);
  fireEvent.click(screen.getByRole("button", { name: "저장된 검사 상태 조회" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("codex_preflight_failed");
  expect(screen.getByRole("alert")).toHaveTextContent("safe-id");
  expect(screen.queryByText("DO_NOT_SHOW_PROVIDER_DETAIL")).not.toBeInTheDocument();
  expect(calls).toEqual([{ path: "/api/v1/admin/rag/configuration-versions/another-version/codex-status", method: undefined }]);
});
