import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SavedConfiguration, Workspace } from "../configurations/api";
import type { Domain, DomainConnection } from "../domains/api";
import { ApplyCandidatePanel } from "./ApplyCandidatePanel";

const candidate: SavedConfiguration = {
  id: "candidate", version_id: "candidate-v2", name: "검증한 후보", version: 2,
  owner_id: "owner", document_processing_profile_id: "processing", indexing_profile_id: "indexing",
  retrieval_profile_id: "retrieval", generation_profile_id: "generation", workspace_ids: ["scope-a", "scope-b"],
  answer_policy: { id: "answer-policy", version: 3, mode: "generative", min_semantic_score: .82,
    min_keyword_coverage: .71, require_complete_provenance: true, conflict_mode: "separate_sources" },
  evaluation_state: "passed", is_system: false, is_default: false, experimental: true,
  search_ready: true, answer_ready: true, service_ready: true, search_reasons: [], answer_reasons: [],
  generation_execution_preview: null,
};
const workspaces: Workspace[] = [
  { id: "scope-a", name: "기존 대화 범위", kind: "company", expires_at: null },
  { id: "scope-b", name: "후보에만 있는 범위", kind: "company", expires_at: null },
];
const domain: Domain = {
  id: "domain", slug: "synthetic", display_name: "기존 대화", description: "합성 자료",
  active: true, ready: true, connection_version: { id: "old-connection", version: 1 },
  workspace_options: [workspaces[0]], generation_execution_preview: null,
  readiness: { search_ready: true, answer_ready: true, service_ready: true, reason_codes: [] },
};
const oldConnection: DomainConnection = {
  id: "old-connection", domain_id: "domain", version: 1, configuration_version_id: "old-candidate",
  configuration_name: "기존 구성", configuration_version: 1, workspace_ids: ["scope-a"],
  created_by: "owner", created_at: "2026-10-30T00:00:00Z",
};
const newConnection: DomainConnection = {
  ...oldConnection, id: "new-connection", version: 2, configuration_version_id: candidate.version_id,
  configuration_name: candidate.name, configuration_version: 2,
};
const configurationsPath = "/api/v1/rag/configurations";
const domainsPath = "/api/v1/admin/rag/domains";
const connectionsPath = `${domainsPath}/domain/connections`;
const activatePath = `${connectionsPath}/new-connection/activate`;
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status, headers: { "content-type": "application/json" },
});
type Request = { path: string; method: string; body?: unknown };
type Server = {
  calls: Request[];
  configurations: SavedConfiguration[];
  domain: Domain;
  connections: DomainConnection[];
  hook?: (request: Request, server: Server) => Response | Promise<Response> | undefined;
};
function server(): Server {
  const state: Server = { calls: [], configurations: [candidate], domain, connections: [oldConnection] };
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input, init) => {
    const request = { path: String(input), method: init?.method ?? "GET",
      ...(init?.body ? { body: JSON.parse(String(init.body)) as unknown } : {}) };
    state.calls.push(request);
    const intercepted = state.hook?.(request, state);
    if (intercepted) return intercepted;
    if (request.path === configurationsPath) return json(state.configurations);
    if (request.path === domainsPath) return json([state.domain]);
    if (request.path === connectionsPath && request.method === "GET") return json(state.connections);
    if (request.path === connectionsPath && request.method === "POST") {
      state.connections = [...state.connections, newConnection];
      return json(newConnection, 201);
    }
    if (request.path === activatePath && request.method === "POST") {
      state.domain = { ...state.domain, connection_version: { id: "new-connection", version: 2 } };
      return json({ id: "domain", slug: "synthetic", display_name: domain.display_name,
        active_connection_version_id: "new-connection" });
    }
    throw new Error(`Unexpected request ${request.method} ${request.path}`);
  }));
  return state;
}
function panel(config = candidate, accepted: string | null = candidate.version_id) {
  return render(<ApplyCandidatePanel candidate={config} domains={[domain]} workspaces={workspaces} acceptedVersionId={accepted} />);
}
async function prepare() {
  fireEvent.change(screen.getByLabelText("적용할 대화"), { target: { value: "domain" } });
  fireEvent.click(screen.getByRole("button", { name: "적용 내용 확인" }));
  await screen.findByLabelText("이 대화를 사용하는 사용자에게 새 모델을 적용합니다.");
}
function confirmAndApply() {
  fireEvent.click(screen.getByLabelText("이 대화를 사용하는 사용자에게 새 모델을 적용합니다."));
  fireEvent.click(screen.getByRole("button", { name: "이 대화에 적용" }));
}
const writes = (state: Server) => state.calls.filter(item => item.method !== "GET");
afterEach(() => vi.unstubAllGlobals());

describe("independent guided application boundary", () => {
  it.each([null, "different-version"])("does not treat search evaluation or a different receipt as answer acceptance (%s)", receipt => {
    const state = server(); panel(candidate, receipt);
    expect(screen.getByLabelText("적용할 대화")).toBeDisabled();
    expect(screen.getByRole("button", { name: "적용 내용 확인" })).toBeDisabled();
    expect(state.calls).toEqual([]);
  });

  it.each(["pending", "failed"] as const)("blocks a %s candidate even with an exact receipt", evaluation_state => {
    const state = server(); panel({ ...candidate, evaluation_state });
    expect(screen.getByLabelText("적용할 대화")).toBeDisabled();
    expect(state.calls).toEqual([]);
  });

  it("uses only the existing conversation scope and requires an explicit second action", async () => {
    const state = server(); panel();
    expect(state.calls).toEqual([]);
    await prepare();
    expect(writes(state)).toEqual([]);
    expect(screen.getByRole("button", { name: "이 대화에 적용" })).toBeDisabled();
    expect(screen.getByText("지식 공간: 기존 대화 범위")).toBeVisible();
    confirmAndApply();
    await screen.findByRole("link", { name: "대화 열기" });
    expect(writes(state)).toEqual([
      { path: connectionsPath, method: "POST", body: { configuration_version_id: candidate.version_id, workspace_ids: ["scope-a"] } },
      { path: activatePath, method: "POST" },
    ]);
    expect(state.calls.some(item => /default|generative-evaluations/.test(item.path))).toBe(false);
  });

  it("blocks when the latest candidate loses readiness after preview", async () => {
    const state = server(); panel(); await prepare();
    state.configurations = [{ ...candidate, answer_ready: false, service_ready: false }];
    confirmAndApply();
    await screen.findByRole("alert");
    expect(writes(state)).toEqual([]);
    expect(screen.queryByLabelText("이 대화를 사용하는 사용자에게 새 모델을 적용합니다.")).not.toBeInTheDocument();
  });

  it("blocks when a different connection becomes active after preview", async () => {
    const state = server(); panel(); await prepare();
    state.domain = { ...domain, connection_version: { id: "another-connection", version: 3 } };
    confirmAndApply();
    await screen.findByRole("alert");
    expect(writes(state)).toEqual([]);
  });

  it("rechecks the active connection after saving an inactive connection", async () => {
    const state = server();
    state.hook = request => {
      if (request.path === connectionsPath && request.method === "POST") {
        state.connections = [...state.connections, newConnection];
        state.domain = { ...domain, connection_version: { id: "concurrent-connection", version: 3 } };
        return json(newConnection, 201);
      }
    };
    panel(); await prepare(); confirmAndApply();
    await screen.findByRole("alert");
    expect(writes(state).map(item => item.path)).toEqual([connectionsPath]);
    expect(state.domain.connection_version?.id).toBe("concurrent-connection");
  });

  it("reuses the committed inactive connection after its list response was lost", async () => {
    const state = server(); let loseList = false;
    state.hook = request => {
      if (request.path === connectionsPath && request.method === "POST") {
        state.connections = [...state.connections, newConnection]; loseList = true;
        return json(newConnection, 201);
      }
      if (request.path === connectionsPath && request.method === "GET" && loseList) {
        loseList = false; return Promise.reject(new TypeError("Synthetic lost response"));
      }
    };
    panel(); await prepare(); confirmAndApply();
    await screen.findByRole("alert");
    expect(state.domain.connection_version?.id).toBe("old-connection");
    await prepare(); confirmAndApply();
    await screen.findByRole("link", { name: "대화 열기" });
    expect(writes(state).filter(item => item.path === connectionsPath)).toHaveLength(1);
    expect(writes(state).filter(item => item.path === activatePath)).toHaveLength(1);
  });

  it("does not reuse an existing candidate connection with a different scope", async () => {
    const state = server();
    state.connections.push({ ...newConnection, id: "wrong-scope-connection", workspace_ids: ["scope-a", "scope-b"] });
    panel(); await prepare(); confirmAndApply();
    await screen.findByRole("link", { name: "대화 열기" });
    expect(writes(state)[0]).toMatchObject({ path: connectionsPath, body: { workspace_ids: ["scope-a"] } });
    expect(writes(state)[1].path).toBe(activatePath);
  });

  it("reconciles a lost activation response without issuing a second activation", async () => {
    const state = server(); state.connections.push(newConnection);
    state.hook = request => {
      if (request.path === activatePath) {
        state.domain = { ...domain, connection_version: { id: "new-connection", version: 2 } };
        return Promise.reject(new TypeError("Synthetic lost activation response"));
      }
    };
    panel(); await prepare(); confirmAndApply();
    await screen.findByRole("link", { name: "대화 열기" });
    expect(writes(state).map(item => item.path)).toEqual([activatePath]);
  });

  it("prevents repeated activation clicks while a request is pending", async () => {
    const state = server(); state.connections.push(newConnection);
    let finish!: (response: Response) => void;
    state.hook = request => request.path === activatePath ? new Promise<Response>(resolve => { finish = resolve; }) : undefined;
    panel(); await prepare();
    fireEvent.click(screen.getByLabelText("이 대화를 사용하는 사용자에게 새 모델을 적용합니다."));
    const apply = screen.getByRole("button", { name: "이 대화에 적용" });
    act(() => { fireEvent.click(apply); fireEvent.click(apply); });
    await waitFor(() => expect(writes(state)).toHaveLength(1));
    expect(apply).toBeDisabled();
    await act(async () => finish(json({ active_connection_version_id: "new-connection" })));
    await screen.findByRole("link", { name: "대화 열기" });
    expect(writes(state)).toHaveLength(1);
  });
});
