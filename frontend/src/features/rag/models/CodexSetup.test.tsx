import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { CodexDeploymentForm } from "./CodexDeploymentForm";
import { CodexGenerationForm } from "./CodexGenerationForm";
import { CodexEvidenceApproval } from "./CodexEvidenceApproval";
import { LlmModelForm } from "./LlmModelForm";
import type { CodexEvidence, CodexRunner, DeploymentSummary } from "./api";

export const runner: CodexRunner = {
  runner_ref: "personal-runner", cli_version: "1.2.3", local_preflight_passed: true,
  safe_error_code: null, limits: { timeout_seconds: 60, max_output_tokens: 2048, max_concurrent: 1 },
  prompt_options: [{ answer_ref: "answer-test", context_ref: "context-test", control_ref: "control-test",
    response_schema_version: 2, control_text: "Trusted control", answer_text: "Trusted answer", context_text: "Trusted context" }],
};
export const deployment: DeploymentSummary = {
  deployment_id: "d", version_id: "dv", version: 1, display_name: "Test Codex", description: "",
  model_name: "Test model", model_version: 1, provider: "development_codex_exec",
  provider_model_id: "configured-model", runner_ref: "personal-runner", location: "external",
  external_transfer: true, allowed_environments: ["development"], capabilities: ["structured_output"],
  secret_configured: false, readiness: { ready: false, reason_codes: ["deployment_not_ready"] }, latest_health: null,
};
afterEach(() => vi.unstubAllGlobals());
const json = (value: unknown, init: ResponseInit = {}) => new Response(JSON.stringify(value), {
  ...init,
  headers: { "content-type": "application/json", ...init.headers },
});
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((complete) => { resolve = complete; });
  return { promise, resolve };
}
const evidence = (overrides: Partial<CodexEvidence> = {}): CodexEvidence => ({
  revision_id: "exact-revision",
  document_id: "doc",
  document_name: "Synthetic",
  revision_number: 1,
  workspace_id: "w",
  content_sha256: "a".repeat(64),
  approval_classification: null,
  approved_at: null,
  revoked: false,
  approval_generation: 0,
  provider: "development_codex_exec",
  approval_history: [],
  ...overrides,
});

it("creates a runner deployment with editable model identity and no credentials", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json(deployment)); vi.stubGlobal("fetch", fetcher);
  render(<CodexDeploymentForm runners={[runner]} models={[{ id: "m", kind: "llm", name: "Model", version: 1, config: { model_identifier: "custom-model" } }]} onSaved={() => {}} />);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("배포 이름"), { target: { value: "New deployment" } });
  fireEvent.change(screen.getByLabelText("요청 모델 ID"), { target: { value: "owner-selected-model" } });
  fireEvent.click(screen.getByRole("button", { name: "Codex 배포 버전 등록" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  const body = JSON.parse(fetcher.mock.calls[0][1]!.body as string);
  expect(body).toMatchObject({ provider_model_id: "owner-selected-model", runner_ref: "personal-runner", endpoint_ref: null, secret_ref: null, max_retries: 0, healthcheck_enabled: false });
  expect(document.querySelector('input[type="password"]')).toBeNull();
});

it("saves an unverified deployment generation profile using trusted prompt options", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json({ id: "profile" })); vi.stubGlobal("fetch", fetcher);
  render(<CodexGenerationForm deployments={[deployment]} runners={[runner]} onSaved={() => {}} />);
  expect(screen.getByText("Trusted control")).toBeVisible();
  fireEvent.change(screen.getByLabelText("생성 프로파일 이름"), { target: { value: "New profile" } });
  fireEvent.click(screen.getByRole("button", { name: "Codex 생성 프로파일 등록" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  const wire = JSON.parse(JSON.parse(fetcher.mock.calls[0][1]!.body as string).content);
  expect(wire).toMatchObject({ deployment_version_id: "dv", config: { prompt_ref: "answer-test", context_prompt_ref: "context-test", citation_mode: "required" } });
});

it("shows empty runner catalog without inventing an executable option", () => {
  render(<CodexDeploymentForm runners={[]} models={[]} onSaved={() => {}} />);
  expect(screen.getByText(/등록된 Codex runner가 없습니다/)).toBeVisible();
  expect(screen.queryByRole("button", { name: "Codex 배포 버전 등록" })).not.toBeInTheDocument();
});

it("requires fresh classification and consent before reapproving a revoked document", async () => {
  const fetcher = vi.fn(async () => json([evidence({
    revoked: true,
    approval_generation: 2,
    approved_at: "2026-09-09T01:00:00Z",
    approval_history: [
      { action: "approve", generation: 1, actor_id: "owner", occurred_at: "2026-09-09T01:00:00Z", classification: "synthetic" },
      { action: "revoke", generation: 2, actor_id: null, occurred_at: "2026-09-09T02:00:00Z", classification: "synthetic" },
    ],
  })]));
  vi.stubGlobal("fetch", fetcher);
  render(<CodexEvidenceApproval workspaces={[{ id: "w", name: "Synthetic workspace", kind: "personal", expires_at: null }]} />);
  fireEvent.click(screen.getByRole("button", { name: "문서 revision 불러오기" }));
  const button = await screen.findByRole("button", { name: "다시 승인" });
  expect(button).toBeDisabled();
  expect(screen.getAllByText(/development_codex_exec/)[0]).toBeVisible();
  expect(screen.getByRole("link", { name: "이 버전 원문 확인" })).toHaveAttribute(
    "href",
    "/workshop/workspaces/w/documents?document=doc&version=exact-revision",
  );
  expect(screen.getByText("기술 식별자와 해시").closest("details")).not.toHaveAttribute("open");
  expect(screen.getByText("승인 이력 (2건)").closest("details")).not.toHaveAttribute("open");
  fireEvent.change(screen.getByLabelText("자료 분류"), { target: { value: "public" } });
  expect(button).toBeDisabled();
  fireEvent.click(screen.getByRole("checkbox", { name: /외부 전송에 동의/ }));
  expect(button).toBeEnabled();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("connects each classification to its visible guidance without granting consent", async () => {
  const fetcher = vi.fn(async () => json([evidence(), evidence({ revision_id: "second-revision", document_id: "second-doc" })]));
  vi.stubGlobal("fetch", fetcher);
  render(<CodexEvidenceApproval workspaces={[{ id: "w", name: "Synthetic workspace", kind: "personal", expires_at: null }]} />);
  fireEvent.click(screen.getByRole("button", { name: "문서 revision 불러오기" }));
  const classifications = await screen.findAllByRole("combobox", { name: "자료 분류" });
  const helpIds = classifications.map((select) => select.getAttribute("aria-describedby"));
  expect(new Set(helpIds).size).toBe(2);
  for (const select of classifications) {
    const help = document.getElementById(select.getAttribute("aria-describedby")!);
    expect(help).toBeVisible();
    expect(select).toHaveAccessibleDescription(/이미 공개되어 있으며.*외부 전송해도 되는지 확인한 자료/);
    expect(select).toHaveAccessibleDescription(/실제 개인정보·기밀 등 민감정보가 없는 가상·테스트 자료.*AI가 만든 자료만을 뜻하지 않습니다/);
    expect(select).toHaveAccessibleDescription(/두 분류에 모두 해당하면 합성 자료를 선택/);
    expect(select).toHaveAccessibleDescription(/자동으로 익명화하거나 사이트에 공개하지 않으며, AI를 자동 실행하지 않습니다/);
    fireEvent.change(select, { target: { value: "synthetic" } });
  }
  for (const checkbox of screen.getAllByRole("checkbox", { name: /외부 전송에 동의/ })) expect(checkbox).not.toBeChecked();
  for (const button of screen.getAllByRole("button", { name: "외부 전송 자료 승인" })) expect(button).toBeDisabled();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("keeps classification guidance visible for approved evidence without requiring revocation", async () => {
  const fetcher = vi.fn(async () => json([evidence({ approval_classification: "synthetic", approval_generation: 1 })]));
  vi.stubGlobal("fetch", fetcher);
  render(<CodexEvidenceApproval workspaces={[{ id: "w", name: "Synthetic workspace", kind: "personal", expires_at: null }]} />);
  fireEvent.click(screen.getByRole("button", { name: "문서 revision 불러오기" }));
  expect(await screen.findByText("승인 분류: 합성")).toBeVisible();
  expect(screen.getByText(/^공개 자료: 이미 공개되어 있으며/)).toBeVisible();
  expect(screen.getByText(/^합성 자료: 실제 개인정보/)).toBeVisible();
  expect(screen.getByText(/두 분류에 모두 해당하면 합성 자료를 선택/)).toBeVisible();
  expect(screen.getByText(/자동으로 익명화하거나 사이트에 공개하지 않으며, AI를 자동 실행하지 않습니다/)).toBeVisible();
  expect(screen.queryByRole("combobox", { name: "자료 분류" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "이 revision 승인 취소" })).toBeDisabled();
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("registers a provider-independent LLM identity without automatic verification", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => json({ id: "m", kind: "llm", name: "Identity", version: 2, config: { model_identifier: "changed-model" } }));
  vi.stubGlobal("fetch", fetcher);
  render(<LlmModelForm onSaved={() => {}} />);
  fireEvent.change(screen.getByLabelText("LLM 정의 이름"), { target: { value: "Identity" } });
  fireEvent.change(screen.getByLabelText("모델 식별자"), { target: { value: "changed-model" } });
  fireEvent.click(screen.getByRole("button", { name: "LLM 정의 버전 등록" }));
  await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toMatchObject({ kind: "llm", config: { model_identifier: "changed-model" } });
});

it("does not load a prior workspace after an evidence approval completes late", async () => {
  const calls: string[] = [];
  let finish!: () => void;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    calls.push(String(input));
    if (init?.method === "POST") return new Promise<Response>((resolve) => { finish = () => resolve(new Response(null, { status: 204 })); });
    return json([evidence({ revision_id: "rev", workspace_id: "first" })]);
  }));
  render(<CodexEvidenceApproval workspaces={[{ id: "first", name: "First", kind: "personal", expires_at: null }, { id: "second", name: "Second", kind: "personal", expires_at: null }]} />);
  fireEvent.click(screen.getByRole("button", { name: "문서 revision 불러오기" }));
  await screen.findByText("Synthetic · revision 1");
  fireEvent.change(screen.getByLabelText("자료 분류"), { target: { value: "synthetic" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /외부 전송에 동의/ }));
  fireEvent.click(screen.getByRole("button", { name: "외부 전송 자료 승인" }));
  fireEvent.change(screen.getByLabelText("자료 지식 공간"), { target: { value: "second" } });
  finish();
  await waitFor(() => expect(screen.queryByText("Synthetic · revision 1")).not.toBeInTheDocument());
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(calls).toHaveLength(2);
});

it("uses exact generations and a different request id for approval and revocation", async () => {
  const mutations: RequestInit[] = [];
  let current = evidence();
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST" || init?.method === "DELETE") {
      expect(String(input)).toBe("/api/v1/admin/rag/codex-evidence/exact-revision/approval");
      mutations.push(init);
      current = init.method === "POST"
        ? evidence({ approval_classification: "public", approved_at: "2026-09-09T01:00:00Z", approval_generation: 1,
          approval_history: [{ action: "approve", generation: 1, actor_id: "owner", occurred_at: "2026-09-09T01:00:00Z", classification: "public" }] })
        : evidence({ revoked: true, approved_at: "2026-09-09T01:00:00Z", approval_generation: 2,
          approval_history: [
            { action: "approve", generation: 1, actor_id: "owner", occurred_at: "2026-09-09T01:00:00Z", classification: "public" },
            { action: "revoke", generation: 2, actor_id: "owner", occurred_at: "2026-09-09T02:00:00Z", classification: "public" },
          ] });
      return new Response(null, { status: 204 });
    }
    return json([current]);
  }));
  render(<CodexEvidenceApproval workspaces={[{ id: "w", name: "Synthetic workspace", kind: "personal", expires_at: null }]} />);
  fireEvent.click(screen.getByRole("button", { name: "문서 revision 불러오기" }));
  await screen.findByText("Synthetic · revision 1");
  expect(screen.getByRole("button", { name: "외부 전송 자료 승인" })).toBeDisabled();
  fireEvent.change(screen.getByLabelText("자료 분류"), { target: { value: "public" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /외부 전송에 동의/ }));
  fireEvent.click(screen.getByRole("button", { name: "외부 전송 자료 승인" }));
  await waitFor(() => expect(mutations).toHaveLength(1));
  expect(await screen.findByRole("button", { name: "이 revision 승인 취소" })).toBeDisabled();
  const approvalBody = JSON.parse(String(mutations[0].body));
  expect(approvalBody).toMatchObject({ classification: "public", content_sha256: "a".repeat(64), expected_generation: 0 });
  expect(approvalBody.request_id).toMatch(/^[0-9a-f-]{36}$/);
  fireEvent.click(screen.getByRole("checkbox", { name: /이미 전송된 자료는 회수되지 않음/ }));
  fireEvent.click(screen.getByRole("button", { name: "이 revision 승인 취소" }));
  expect(await screen.findByRole("button", { name: "다시 승인" })).toBeDisabled();
  expect(mutations).toHaveLength(2);
  const revocationBody = JSON.parse(String(mutations[1].body));
  expect(revocationBody).toMatchObject({ expected_generation: 1 });
  expect(revocationBody.request_id).not.toBe(approvalBody.request_id);
  expect(mutations[1].headers).toMatchObject({ "x-codex-request": "1", "content-type": "application/json" });
});

it("shows approval processing until a pending POST fails, then offers an exact retry", async () => {
  const post = deferred<Response>();
  vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") return post.promise;
    return json([evidence()]);
  }));
  render(<CodexEvidenceApproval workspaces={[{ id: "w", name: "Synthetic workspace", kind: "personal", expires_at: null }]} />);
  fireEvent.click(screen.getByRole("button", { name: "문서 revision 불러오기" }));
  await screen.findByText("Synthetic · revision 1");
  fireEvent.change(screen.getByLabelText("자료 분류"), { target: { value: "public" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /외부 전송에 동의/ }));
  fireEvent.click(screen.getByRole("button", { name: "외부 전송 자료 승인" }));
  expect(await screen.findByText("상태: 승인 처리 중 · 승인 세대 0")).toBeVisible();
  expect(screen.getByRole("button", { name: "승인 처리 중…" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "동일 승인 요청 다시 시도" })).not.toBeInTheDocument();
  post.resolve(json({ error: { code: "request_failed", message: "uncertain", correlation_id: "post" } }, { status: 503 }));
  expect(await screen.findByRole("button", { name: "동일 승인 요청 다시 시도" })).toBeEnabled();
  expect(screen.getByText("상태: 미승인 · 승인 세대 0")).toBeVisible();
});

it("shows revocation processing and retries a failed DELETE with the same request", async () => {
  const firstDelete = deferred<Response>();
  const bodies: string[] = [];
  let current = evidence({ approval_classification: "synthetic", approved_at: "2026-09-09T01:00:00Z", approval_generation: 3 });
  vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "DELETE") {
      bodies.push(String(init.body));
      if (bodies.length === 1) return firstDelete.promise;
      current = evidence({ revoked: true, approved_at: "2026-09-09T01:00:00Z", approval_generation: 4 });
      return new Response(null, { status: 204 });
    }
    return json([current]);
  }));
  render(<CodexEvidenceApproval workspaces={[{ id: "w", name: "Synthetic workspace", kind: "personal", expires_at: null }]} />);
  fireEvent.click(screen.getByRole("button", { name: "문서 revision 불러오기" }));
  await screen.findByText("승인 분류: 합성");
  fireEvent.click(screen.getByRole("checkbox", { name: /이미 전송된 자료는 회수되지 않음/ }));
  fireEvent.click(screen.getByRole("button", { name: "이 revision 승인 취소" }));
  expect(await screen.findByText("상태: 승인 취소 처리 중 · 승인 세대 3")).toBeVisible();
  expect(screen.getByRole("button", { name: "승인 취소 처리 중…" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "동일 승인 취소 요청 다시 시도" })).not.toBeInTheDocument();
  firstDelete.resolve(json({ error: { code: "request_failed", message: "uncertain", correlation_id: "delete" } }, { status: 503 }));
  fireEvent.click(await screen.findByRole("button", { name: "동일 승인 취소 요청 다시 시도" }));
  await screen.findByRole("button", { name: "다시 승인" });
  expect(bodies).toHaveLength(2);
  expect(bodies[1]).toBe(bodies[0]);
});

it("retries an uncertain approval with the same request id and payload", async () => {
  const bodies: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") {
      bodies.push(String(init.body));
      if (bodies.length === 1) return json({ error: { code: "request_failed", message: "uncertain", correlation_id: "retry" } }, { status: 503 });
      return new Response(null, { status: 204 });
    }
    return json([evidence()]);
  }));
  render(<CodexEvidenceApproval workspaces={[{ id: "w", name: "Synthetic workspace", kind: "personal", expires_at: null }]} />);
  fireEvent.click(screen.getByRole("button", { name: "문서 revision 불러오기" }));
  await screen.findByText("Synthetic · revision 1");
  fireEvent.change(screen.getByLabelText("자료 분류"), { target: { value: "synthetic" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /외부 전송에 동의/ }));
  fireEvent.click(screen.getByRole("button", { name: "외부 전송 자료 승인" }));
  fireEvent.click(await screen.findByRole("button", { name: "동일 승인 요청 다시 시도" }));
  await waitFor(() => expect(bodies).toHaveLength(2));
  expect(bodies[1]).toBe(bodies[0]);
});

it("reloads a stale generation on conflict and requires consent again without auto-resubmitting", async () => {
  let generation = 2;
  const mutations: RequestInit[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") {
      mutations.push(init);
      return json({ error: { code: "codex_evidence_approval_conflict", message: "stale", correlation_id: "conflict" } }, { status: 409 });
    }
    const response = evidence({ revoked: true, approval_generation: generation,
      approval_history: [{ action: "revoke", generation, actor_id: "owner", occurred_at: "2026-09-09T02:00:00Z", classification: "synthetic" }] });
    generation = 4;
    return json([response]);
  }));
  render(<CodexEvidenceApproval workspaces={[{ id: "w", name: "Synthetic workspace", kind: "personal", expires_at: null }]} />);
  fireEvent.click(screen.getByRole("button", { name: "문서 revision 불러오기" }));
  const firstButton = await screen.findByRole("button", { name: "다시 승인" });
  fireEvent.change(screen.getByLabelText("자료 분류"), { target: { value: "public" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /외부 전송에 동의/ }));
  fireEvent.click(firstButton);
  expect(await screen.findByText(/최신 상태를 다시 불러왔습니다/)).toBeVisible();
  expect(screen.getByRole("button", { name: "다시 승인" })).toBeDisabled();
  expect(screen.getByRole("checkbox", { name: /외부 전송에 동의/ })).not.toBeChecked();
  expect(mutations).toHaveLength(1);
});

it("locks a conflicted card when refresh fails and manually reconciles without resubmitting", async () => {
  let gets = 0;
  let posts = 0;
  vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "POST") {
      posts += 1;
      return json({ error: { code: "codex_evidence_approval_conflict", message: "stale", correlation_id: "conflict-refresh" } }, { status: 409 });
    }
    gets += 1;
    if (gets === 2) return json({ error: { code: "request_failed", message: "refresh", correlation_id: "refresh" } }, { status: 503 });
    return json([evidence({ revoked: true, approval_generation: gets > 2 ? 4 : 2 })]);
  }));
  render(<CodexEvidenceApproval workspaces={[{ id: "w", name: "Synthetic workspace", kind: "personal", expires_at: null }]} />);
  fireEvent.click(screen.getByRole("button", { name: "문서 revision 불러오기" }));
  const approve = await screen.findByRole("button", { name: "다시 승인" });
  fireEvent.change(screen.getByLabelText("자료 분류"), { target: { value: "synthetic" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /외부 전송에 동의/ }));
  fireEvent.click(approve);
  expect(await screen.findByText(/최신 상태를 다시 불러오지 못했습니다/)).toBeVisible();
  expect(screen.getByRole("button", { name: "다시 승인" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "문서 상태 다시 불러오기" }));
  expect(await screen.findByText("상태: 승인 취소 · 승인 세대 4")).toBeVisible();
  expect(screen.getByRole("checkbox", { name: /외부 전송에 동의/ })).not.toBeChecked();
  expect(screen.getByRole("button", { name: "다시 승인" })).toBeDisabled();
  expect(posts).toBe(1);
});

it("reports a committed approval separately when its refresh fails and reconciles without another POST", async () => {
  let gets = 0;
  const methods: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
    methods.push(init?.method ?? "GET");
    if (init?.method === "POST") return new Response(null, { status: 204 });
    gets += 1;
    if (gets === 2) return json({ error: { code: "request_failed", message: "refresh", correlation_id: "refresh" } }, { status: 503 });
    return json([evidence({ approval_classification: gets > 2 ? "public" : null, approval_generation: gets > 2 ? 1 : 0 })]);
  }));
  render(<CodexEvidenceApproval workspaces={[{ id: "w", name: "Synthetic workspace", kind: "personal", expires_at: null }]} />);
  fireEvent.click(screen.getByRole("button", { name: "문서 revision 불러오기" }));
  await screen.findByText("Synthetic · revision 1");
  fireEvent.change(screen.getByLabelText("자료 분류"), { target: { value: "public" } });
  fireEvent.click(screen.getByRole("checkbox", { name: /외부 전송에 동의/ }));
  fireEvent.click(screen.getByRole("button", { name: "외부 전송 자료 승인" }));
  expect(await screen.findByRole("status")).toHaveTextContent("승인 요청은 완료되었지만 최신 상태를 불러오지 못했습니다");
  fireEvent.click(screen.getByRole("button", { name: "문서 상태 다시 불러오기" }));
  expect(await screen.findByText("승인 분류: 공개")).toBeVisible();
  expect(methods.filter((method) => method === "POST")).toHaveLength(1);
});
