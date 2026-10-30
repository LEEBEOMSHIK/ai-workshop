import { useEffect } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { SavedConfiguration } from "../configurations/api";
import type { DeploymentSummary, ProfileSummary } from "../models/api";
import { ModelSetupPage, type ModelSetupData } from "./ModelSetupPage";

const probe = vi.hoisted(() => ({
  modelMounts: 0,
  saves: [] as Array<(candidate: SavedConfiguration, profile: ProfileSummary) => void>,
}));
vi.mock("./ModelConnectionPanel", () => ({ ModelConnectionPanel: ({ selectedDeploymentId, deployments, onSelectDeployment }: {
  selectedDeploymentId: string; deployments: DeploymentSummary[]; onSelectDeployment: (id: string) => void;
}) => {
  useEffect(() => { probe.modelMounts += 1; }, []);
  return <label>모의 모델 연결<select value={selectedDeploymentId} onChange={event => onSelectDeployment(event.target.value)}>
    <option value="">선택</option>{deployments.map(item => <option key={item.version_id} value={item.version_id}>{item.display_name}</option>)}
  </select></label>;
} }));
vi.mock("./RagCandidatePanel", () => ({ RagCandidatePanel: ({ onSaved }: {
  onSaved: (candidate: SavedConfiguration, profile: ProfileSummary) => void;
}) => { probe.saves.push(onSaved); return <p>모의 후보 작성</p>; } }));
vi.mock("../configurations/GenerativeEvaluationPanel", () => ({ GenerativeEvaluationPanel: ({ configurations, onAccepted }: {
  configurations: SavedConfiguration[]; onAccepted: (receipt: { configuration_version_id: string }) => void;
}) => <div>
  <button onClick={() => onAccepted({ configuration_version_id: "unrelated-version" })}>다른 구성 수용</button>
  <button onClick={() => onAccepted({ configuration_version_id: configurations[0].version_id })}>선택 구성 수용</button>
</div> }));
vi.mock("./ApplyCandidatePanel", () => ({ ApplyCandidatePanel: ({ candidate, acceptedVersionId }: {
  candidate: SavedConfiguration; acceptedVersionId: string | null;
}) => <p data-testid="apply-state">{candidate.version_id}:{acceptedVersionId ?? "unaccepted"}</p> }));

function configuration(suffix: string): SavedConfiguration {
  return {
    id: `configuration-${suffix}`, version_id: `candidate-${suffix}`, version: 1, name: `구성 ${suffix}`,
    owner_id: "owner", document_processing_profile_id: "processing", indexing_profile_id: "indexing",
    retrieval_profile_id: "retrieval", generation_profile_id: `profile-${suffix}`, workspace_ids: ["scope"],
    answer_policy: { id: "answer-policy", version: 1, mode: "generative", min_semantic_score: .8,
      min_keyword_coverage: .7, require_complete_provenance: true, conflict_mode: "separate_sources" },
    evaluation_state: "passed", is_system: false, is_default: false, experimental: true,
    search_ready: true, answer_ready: true, service_ready: true, search_reasons: [], answer_reasons: [],
    generation_execution_preview: null,
  };
}
function deployment(suffix: string): DeploymentSummary {
  return {
    deployment_id: `deployment-${suffix}`, version_id: `deployment-version-${suffix}`, version: 1,
    display_name: `모델 ${suffix}`, description: "합성 연결", model_name: `model-${suffix}`, model_version: 1,
    provider: "local_openai_compatible", provider_model_id: `synthetic-model-${suffix}`, location: "local",
    external_transfer: false, allowed_environments: ["development"], capabilities: ["structured_output"],
    secret_configured: false, readiness: { ready: true, reason_codes: [] },
    latest_health: { status: "ready", safe_error_code: null, observed_provider_model_id: `synthetic-model-${suffix}`,
      latency_ms: 1, checked_at: "2026-10-30T00:00:00Z" },
  };
}
function profile(suffix: string): ProfileSummary {
  return { id: `profile-${suffix}`, kind: "generation", name: `답변 ${suffix}`, version: 1,
    config: {}, bindings: [], deployment_version_id: `deployment-version-${suffix}`,
    evaluation_state: "draft", is_default: false, legacy: false, readiness: { ready: true, reason_codes: [] } };
}
function data(): ModelSetupData {
  return { models: [], profiles: [profile("a"), profile("b")], configurations: [configuration("a"), configuration("b")],
    deployments: [deployment("a"), deployment("b")], domains: [], workspaces: [],
    options: { endpoints: [], secret_references: [], environment: "development", generation_presets: [] } };
}
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } });
function mockServer(current: ModelSetupData) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input); calls.push(`${init?.method ?? "GET"} ${path}`);
    if (path.endsWith("/health-check")) return json({ status: "ready" });
    if (path === "/api/v1/rag/configurations") return json(current.configurations);
    if (path === "/api/v1/admin/rag/deployments") return json(current.deployments);
    if (path === "/api/v1/admin/rag/domains") return json(current.domains);
    if (path === "/api/v1/rag/models") return json(current.models);
    if (path.startsWith("/api/v1/rag/profiles/")) return json(current.profiles.filter(item => item.kind === path.split("/").at(-1)));
    if (path === "/api/v1/workspaces") return json(current.workspaces);
    if (path === "/api/v1/admin/rag/deployment-setup-options") return json(current.options);
    throw new Error(`Unexpected request: ${path}`);
  }));
  return calls;
}
function chooseModel(suffix: string) {
  fireEvent.change(screen.getByLabelText("모의 모델 연결"), { target: { value: `deployment-version-${suffix}` } });
}
function chooseCandidate(suffix: string) {
  fireEvent.change(screen.getByLabelText("검증할 시험 구성"), { target: { value: `candidate-${suffix}` } });
}
beforeEach(() => { probe.modelMounts = 0; probe.saves = []; });
afterEach(() => vi.unstubAllGlobals());

describe("independent setup orchestration", () => {
  it("does not run health or inference while selecting a saved model and candidate", () => {
    const initial = data(); const calls = mockServer(initial);
    render(<ModelSetupPage initialData={initial} />); chooseModel("a"); chooseCandidate("a");
    expect(screen.getByText(/최근 연결: 정상/)).toBeVisible();
    expect(calls).toEqual([]);
  });

  it("accepts only an exact candidate receipt and clears it when the model changes", () => {
    const initial = data(); mockServer(initial);
    render(<ModelSetupPage initialData={initial} />); chooseModel("a"); chooseCandidate("a");
    fireEvent.click(screen.getByRole("button", { name: "답변 평가 열기" }));
    fireEvent.click(screen.getByRole("button", { name: "다른 구성 수용" }));
    expect(screen.getByTestId("apply-state")).toHaveTextContent("candidate-a:unaccepted");
    fireEvent.click(screen.getByRole("button", { name: "선택 구성 수용" }));
    expect(screen.getByTestId("apply-state")).toHaveTextContent("candidate-a:candidate-a");
    chooseModel("b");
    expect(screen.queryByTestId("apply-state")).not.toBeInTheDocument();
    expect(screen.getByLabelText("검증할 시험 구성")).toHaveValue("");
    chooseModel("a"); chooseCandidate("a");
    expect(screen.getByTestId("apply-state")).toHaveTextContent("candidate-a:unaccepted");
  });

  it("keeps a late saved candidate in its own model without replacing a newer selection", () => {
    const initial = data(); mockServer(initial);
    render(<ModelSetupPage initialData={initial} />); chooseModel("a");
    const receiveOldSave = probe.saves.at(-1)!;
    chooseModel("b"); chooseCandidate("b");
    const late = { ...configuration("a"), id: "late", version_id: "late-version", name: "늦게 저장된 구성" };
    act(() => receiveOldSave(late, profile("a")));
    expect(screen.getByLabelText("모의 모델 연결")).toHaveValue("deployment-version-b");
    expect(screen.getByTestId("apply-state")).toHaveTextContent("candidate-b:unaccepted");
    expect(screen.queryByText(/시험 구성을 저장했습니다/)).not.toBeInTheDocument();
    chooseModel("a");
    expect(screen.getByRole("option", { name: "늦게 저장된 구성 · v1" })).toBeInTheDocument();
    expect(screen.getByLabelText("검증할 시험 구성")).toHaveValue("");
  });

  it("recognizes ready health and refreshes the candidate's answer readiness", async () => {
    const initial = data(); initial.configurations[0] = { ...initial.configurations[0], answer_ready: false, service_ready: false };
    const current = data(); const calls = mockServer(current);
    render(<ModelSetupPage initialData={initial} />); chooseModel("a"); chooseCandidate("a");
    expect(screen.getByText("답변 준비 미완료")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "모델 연결 확인" }));
    await screen.findByText("연결 확인 완료. 답변·인용 품질은 별도 평가가 필요합니다.");
    expect(screen.getByText("답변 준비 완료")).toBeVisible();
    expect(calls.filter(item => item.startsWith("POST"))).toEqual([
      "POST /api/v1/admin/rag/deployment-versions/deployment-version-a/health-check",
    ]);
    expect(calls).toContain("GET /api/v1/rag/configurations");
  });

  it("refreshes catalogs without remounting the registration panel and resetting its write lock", async () => {
    const initial = data(); const calls = mockServer(initial);
    render(<ModelSetupPage initialData={initial} />);
    expect(probe.modelMounts).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "설정 목록 새로 확인" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "설정 목록 새로 확인" })).toBeEnabled());
    expect(probe.modelMounts).toBe(1);
    expect(calls.every(item => item.startsWith("GET"))).toBe(true);
  });
});
