import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { RagCandidatePanel } from "./RagCandidatePanel";
import type { SavedConfiguration, Workspace } from "../configurations/api";
import type { DeploymentSummary, ProfileSummary } from "../models/api";
import type { SetupOptions } from "./setup-api";

const base: SavedConfiguration = {
  id: "config", version_id: "base-version", name: "Original RAG", version: 4,
  document_processing_profile_id: "parser-v2", indexing_profile_id: "index-v3", retrieval_profile_id: "search-v5",
  generation_profile_id: "source-profile", workspace_ids: ["space-b", "space-a"],
  answer_policy: { id: "original-policy", version: 2, mode: "generative", min_semantic_score: 0.83,
    min_keyword_coverage: 0.64, require_complete_provenance: true, conflict_mode: "separate_sources" },
  evaluation_state: "passed", service_ready: true, search_ready: true, answer_ready: true,
  is_system: false, is_default: true, experimental: false, owner_id: "owner",
  search_reasons: [], answer_reasons: [], generation_execution_preview: null,
};
const settings = {
  prompt_ref: "rag-answer-v3", context_prompt_ref: "rag-contextualize-v1", citation_mode: "required",
  context_policy: { max_history_turns: 7, max_history_tokens: 1240 },
  generation: { max_output_tokens: 1477, temperature: 0.13, timeout_seconds: 83, response_schema_version: 2 },
};
const source: ProfileSummary = {
  id: "source-profile", kind: "generation", name: "Original answer settings", version: 3,
  config: settings, deployment_version_id: "original-deployment", bindings: [], legacy: false,
  readiness: { ready: true, reason_codes: [] }, evaluation_state: "passed", is_default: true,
};
const local: DeploymentSummary = {
  deployment_id: "deployment", version_id: "new-deployment", version: 2, display_name: "New local connection", description: "Synthetic",
  model_name: "Synthetic LLM", model_version: 1, provider: "local_openai_compatible", provider_model_id: "exact-model",
  location: "local", external_transfer: false, allowed_environments: ["staging"],
  capabilities: ["structured_output", "contextualization"], secret_configured: false,
  readiness: { ready: true, reason_codes: [] }, latest_health: null,
};
const external: DeploymentSummary = { ...local, version_id: "external-deployment", display_name: "Approved OpenAI", provider: "openai_responses", location: "external", external_transfer: true, secret_configured: true };
const createdProfile: ProfileSummary = { ...source, id: "created-profile", name: "Candidate · 답변", version: 1,
  deployment_version_id: local.version_id, evaluation_state: "draft", is_default: false };
const candidate: SavedConfiguration = { ...base, id: "new-configuration", version_id: "candidate-version", name: "Candidate", version: 1,
  generation_profile_id: createdProfile.id, evaluation_state: "draft", is_default: false, experimental: true,
  answer_ready: false, service_ready: false, answer_reasons: ["evaluation_required"] };
const spaces: Workspace[] = [
  { id: "space-a", name: "Space A", kind: "company", expires_at: null },
  { id: "space-b", name: "Space B", kind: "company", expires_at: null },
];
const options: SetupOptions = { endpoints: [], secret_references: [], environment: "staging", generation_presets: [
  { id: "local-preset", name: "Local preset", description: "Local schema 2", supported_providers: ["local_openai_compatible"], config: settings },
  { id: "external-preset", name: "OpenAI preset", description: "External schema 1", supported_providers: ["openai_responses"],
    config: { ...settings, prompt_ref: "rag-answer-v1", generation: { ...settings.generation, response_schema_version: 1 } } },
] };
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
type Write = { path: string; body: Record<string, unknown> };

function server(handler?: (write: Write, count: number) => Response | Promise<Response>, readProfiles: () => ProfileSummary[] = () => [createdProfile], readConfigurations: () => SavedConfiguration[] = () => []) {
  const writes: Write[] = [];
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (init?.method === "POST") {
      const write = { path, body: JSON.parse(String(init.body)) as Record<string, unknown> };
      writes.push(write);
      return handler ? handler(write, writes.length) : json(path.endsWith("/generation") ? createdProfile : candidate);
    }
    if (path === "/api/v1/rag/configurations") return json(readConfigurations());
    if (path === "/api/v1/rag/profiles/generation") return json(readProfiles());
    if (path === "/api/v1/rag/models" || /^\/api\/v1\/rag\/profiles\//.test(path)) return json([]);
    throw new Error(`Unexpected request ${path}`);
  });
  vi.stubGlobal("fetch", fetcher);
  return { writes, fetcher };
}

function panel(overrides: Partial<Parameters<typeof RagCandidatePanel>[0]> = {}) {
  const onSaved = vi.fn();
  const props = { deployment: local, configurations: [base], profiles: [source], workspaces: spaces, options, onSaved, ...overrides };
  return { ...render(<RagCandidatePanel {...props} />), onSaved, props };
}
function chooseBase(id = "base-version") {
  fireEvent.change(screen.getByLabelText("기반 RAG 구성"), { target: { value: id } });
  fireEvent.change(screen.getByLabelText("후보 이름"), { target: { value: "Candidate" } });
}
function save() { fireEvent.click(screen.getByRole("button", { name: "시험 구성 저장" })); }
afterEach(() => vi.unstubAllGlobals());

it("keeps original source rules and saves Claude's own recipient confirmation", async () => {
  const claude = { ...external, provider: "anthropic_messages" as const, provider_model_id: "claude-test" };
  const config = { ...settings, prompt_ref: "rag-answer-v1", generation: { ...settings.generation,
    response_schema_version: 1, sampling_mode: "provider_default", temperature: 1 } };
  const claudeOptions: SetupOptions = { ...options, generation_presets: [...options.generation_presets,
    { id: "claude-preset", name: "Claude preset", description: "Explicit native settings", supported_providers: ["anthropic_messages"], config }] };
  const api = server(); const view = panel({ deployment: claude, options: claudeOptions }); chooseBase();
  expect(screen.getByRole("alert")).toHaveTextContent("호환되지 않습니다");
  fireEvent.change(screen.getByLabelText("답변 설정"), { target: { value: "preset:claude-preset" } });
  expect(screen.getByLabelText(/Anthropic의 claude-test/)).not.toBeChecked();
  expect(screen.queryByRole("option", { name: "OpenAI preset" })).not.toBeInTheDocument();
  save(); expect(api.writes).toEqual([]);
  fireEvent.click(screen.getByLabelText(/Anthropic의 claude-test/));
  save(); await waitFor(() => expect(view.onSaved).toHaveBeenCalled());
  expect(api.writes[0].body.config).toEqual(config);
  expect(api.writes[1].body).toMatchObject({
    document_processing_profile_id: base.document_processing_profile_id,
    indexing_profile_id: base.indexing_profile_id, retrieval_profile_id: base.retrieval_profile_id,
    workspace_ids: base.workspace_ids,
    external_transfer_approval: { confirmed: true, disclosure_version: "anthropic-generation-v1" },
  });
});

it("copies all existing profile settings and exact source scope without changing the baseline", async () => {
  const originalBase = structuredClone(base), originalSource = structuredClone(source);
  const api = server(); const view = panel(); chooseBase();
  expect(api.writes).toEqual([]);
  expect(screen.getByText("Space B · Space A")).toBeVisible();
  save(); await waitFor(() => expect(view.onSaved).toHaveBeenCalledWith(candidate, createdProfile));
  expect(api.writes).toEqual([
    { path: "/api/v1/admin/rag/profiles/generation", body: {
      name: "Candidate · 답변", version: 1, deployment_version_id: "new-deployment", bindings: [], evaluation_state: "draft",
      config: {
        prompt_ref: "rag-answer-v3", context_prompt_ref: "rag-contextualize-v1", citation_mode: "required",
        context_policy: { max_history_turns: 7, max_history_tokens: 1240 },
        generation: { max_output_tokens: 1477, temperature: 0.13, timeout_seconds: 83, response_schema_version: 2 },
      },
    } },
    { path: "/api/v1/rag/configurations", body: {
      name: "Candidate", document_processing_profile_id: "parser-v2", indexing_profile_id: "index-v3", retrieval_profile_id: "search-v5",
      generation_profile_id: "created-profile", workspace_ids: ["space-b", "space-a"],
      answer_policy: { mode: "generative", min_semantic_score: 0.83, min_keyword_coverage: 0.64, require_complete_provenance: true, conflict_mode: "separate_sources" },
    } },
  ]);
  expect(base).toEqual(originalBase); expect(source).toEqual(originalSource);
});

it("reuses an existing generation profile already bound to the selected deployment", async () => {
  const api = server(); const view = panel({ profiles: [{ ...source, deployment_version_id: local.version_id }] });
  chooseBase(); save(); await waitFor(() => expect(view.onSaved).toHaveBeenCalled());
  expect(api.writes).toHaveLength(1);
  expect(api.writes[0]).toMatchObject({ path: "/api/v1/rag/configurations", body: { generation_profile_id: "source-profile" } });
});

it("retries only the candidate after a known configuration rejection following profile success", async () => {
  const api = server((write, count) => count === 2
    ? json({ error: { code: "invalid_configuration", message: "sensitive policy details", correlation_id: "test" } }, 422)
    : json(write.path.endsWith("/generation") ? createdProfile : candidate));
  const view = panel(); chooseBase(); save();
  expect(await screen.findByRole("alert")).toHaveTextContent(/답변 설정은 저장되어 재사용/);
  expect(screen.queryByText(/sensitive policy details/)).not.toBeInTheDocument();
  save(); await waitFor(() => expect(view.onSaved).toHaveBeenCalledWith(candidate, createdProfile));
  expect(api.writes.map(write => write.path)).toEqual([
    "/api/v1/admin/rag/profiles/generation", "/api/v1/rag/configurations", "/api/v1/rag/configurations",
  ]);
  expect(api.writes[2].body.generation_profile_id).toBe("created-profile");
});

it("recovers lost profile and candidate responses despite JSONB key order and workspace order changes", async () => {
  const reordered: ProfileSummary = { ...createdProfile, config: {
    generation: { response_schema_version: 2, timeout_seconds: 83, temperature: 0.13, max_output_tokens: 1477 },
    citation_mode: "required", context_policy: { max_history_tokens: 1240, max_history_turns: 7 },
    context_prompt_ref: "rag-contextualize-v1", prompt_ref: "rag-answer-v3",
  } };
  const recovered = { ...candidate, workspace_ids: ["space-a", "space-b"] };
  let candidateWritten = false;
  const api = server(write => {
    if (write.path.endsWith("/configurations")) candidateWritten = true;
    throw new TypeError("response lost after commit");
  }, () => [{ ...reordered, id: "wrong-profile", config: { ...reordered.config, citation_mode: "optional" } }, reordered],
  () => candidateWritten ? [recovered] : []);
  const view = panel(); chooseBase(); save();
  expect(await screen.findByRole("alert")).toHaveTextContent(/답변 설정은 저장되어 재사용/);
  expect(view.onSaved).not.toHaveBeenCalled();
  save(); await waitFor(() => expect(view.onSaved).toHaveBeenCalledWith(recovered, reordered));
  expect(api.writes.map(write => write.path)).toEqual(["/api/v1/admin/rag/profiles/generation", "/api/v1/rag/configurations"]);
  expect(api.writes[1].body.generation_profile_id).toBe("created-profile");
});

it("requires explicit confirmation before changing extractive answers to generation", async () => {
  const api = server(); const view = panel({ configurations: [{ ...base, generation_profile_id: null, answer_policy: { ...base.answer_policy, mode: "extractive" } }] });
  chooseBase();
  fireEvent.change(screen.getByLabelText("답변 설정"), { target: { value: "preset:local-preset" } });
  expect(screen.getByRole("button", { name: "시험 구성 저장" })).toBeDisabled(); save(); expect(api.writes).toEqual([]);
  fireEvent.click(screen.getByLabelText(/이 후보에서 추출식 답변/));
  save(); await waitFor(() => expect(view.onSaved).toHaveBeenCalled());
  expect(api.writes[1].body.answer_policy).toEqual({ mode: "generative", min_semantic_score: 0.83,
    min_keyword_coverage: 0.64, require_complete_provenance: true, conflict_mode: "separate_sources" });
});

it("resets external approval when answer settings or source scope change", async () => {
  const compatibleSource: ProfileSummary = { ...source, config: options.generation_presets[1].config };
  const secondBase = { ...base, version_id: "second-base", name: "Other scope", workspace_ids: ["space-a"] };
  const api = server(); const view = panel({ deployment: external, profiles: [compatibleSource], configurations: [base, secondBase] });
  chooseBase();
  const approve = () => fireEvent.click(screen.getByLabelText(/외부 API로 질문/));
  expect(screen.queryByRole("option", { name: "Local preset" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "시험 구성 저장" })).toBeDisabled();
  approve();
  fireEvent.change(screen.getByLabelText("답변 설정"), { target: { value: "preset:external-preset" } });
  expect(screen.getByLabelText(/외부 API로 질문/)).not.toBeChecked();
  expect(screen.getByRole("button", { name: "시험 구성 저장" })).toBeDisabled();
  approve();
  fireEvent.change(screen.getByLabelText("기반 RAG 구성"), { target: { value: "second-base" } });
  expect(screen.getByLabelText(/외부 API로 질문/)).not.toBeChecked();
  expect(screen.getByRole("button", { name: "시험 구성 저장" })).toBeDisabled();
  approve(); save(); await waitFor(() => expect(view.onSaved).toHaveBeenCalled());
  expect(api.writes[1].body).toMatchObject({ workspace_ids: ["space-a"],
    external_transfer_approval: { confirmed: true, disclosure_version: "external-generation-v1" } });
});

it("locks uncertain writes when fresh-list reconciliation fails", async () => {
  const writes: string[] = [];
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
    if (init?.method === "POST") writes.push(String(input));
    throw new TypeError("unavailable server");
  }));
  const view = panel(); chooseBase(); save();
  expect(await screen.findByRole("alert")).toHaveTextContent(/중복 생성을 막기 위해 재저장을 중단/);
  expect(screen.getByRole("button", { name: "시험 구성 저장" })).toBeDisabled();
  expect(screen.getByLabelText("기반 RAG 구성")).toBeDisabled();
  save(); expect(writes).toEqual(["/api/v1/admin/rag/profiles/generation"]);
  expect(view.onSaved).not.toHaveBeenCalled();
});

it("does not submit incompatible OpenAI settings or transform the original profile", () => {
  const api = server(); const snapshot = structuredClone(source); panel({ deployment: external }); chooseBase();
  expect(screen.getByRole("alert")).toHaveTextContent(/호환되지 않습니다/);
  expect(screen.getByRole("button", { name: "시험 구성 저장" })).toBeDisabled();
  save(); expect(api.writes).toEqual([]); expect(source).toEqual(snapshot);
});

it("blocks repeated saves and selection changes while a request is pending", async () => {
  let complete!: (response: Response) => void;
  const pending = new Promise<Response>(resolve => { complete = resolve; });
  const api = server(write => write.path.endsWith("/generation") ? pending : json(candidate));
  const view = panel(); chooseBase();
  const saveButton = screen.getByRole("button", { name: "시험 구성 저장" });
  act(() => { fireEvent.click(saveButton); fireEvent.click(saveButton); });
  expect(api.writes).toHaveLength(1); expect(screen.getByLabelText("기반 RAG 구성")).toBeDisabled();
  await act(async () => complete(json(createdProfile)));
  await waitFor(() => expect(view.onSaved).toHaveBeenCalledTimes(1));
  expect(api.writes).toHaveLength(2);
});

it.each(["name", "scope"])("locks an already saved candidate until its %s changes", async change => {
  const otherBase = { ...base, version_id: "other-base", name: "Other RAG", workspace_ids: ["space-a"] };
  const api = server(); const view = panel({ configurations: [base, otherBase] });
  chooseBase(); save(); await waitFor(() => expect(view.onSaved).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button")).toBeDisabled();
  fireEvent.click(screen.getByRole("button")); expect(api.writes).toHaveLength(2);
  if (change === "name") fireEvent.change(screen.getByLabelText("후보 이름"), { target: { value: "Another candidate" } });
  else fireEvent.change(screen.getByLabelText("기반 RAG 구성"), { target: { value: "other-base" } });
  expect(screen.getByRole("button")).toBeEnabled();
  fireEvent.click(screen.getByRole("button"));
  await waitFor(() => expect(view.onSaved).toHaveBeenCalledTimes(2));
  const last = api.writes.at(-1);
  expect(last?.body).toMatchObject(change === "name" ? { name: "Another candidate" } : { workspace_ids: ["space-a"] });
});
