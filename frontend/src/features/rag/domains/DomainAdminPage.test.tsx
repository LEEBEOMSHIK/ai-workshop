import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import type { SavedConfiguration } from "../configurations/api";
import type { Domain } from "./api";
import { DomainAdminPage } from "./DomainAdminPage";

afterEach(() => vi.unstubAllGlobals());

describe("DomainAdminPage", () => {
  it("registers and edits a domain while keeping its slug immutable", async () => {
    const requests: Array<{ path: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
      requests.push({ path: String(input), body });
      if (init?.method === "POST") return jsonResponse(adminDomain({ display_name: "법률" }), 201);
      return jsonResponse(adminDomain({ display_name: "법률·준법", description: "최신 설명" }));
    }));
    const user = userEvent.setup();
    render(<DomainAdminPage initialData={{ domains: [], configurations: [], workspaces: [], histories: {} }} />);

    await user.type(screen.getByRole("textbox", { name: "도메인 주소" }), "legal");
    await user.type(screen.getByRole("textbox", { name: "표시 이름" }), "법률");
    await user.type(screen.getByRole("textbox", { name: "설명" }), "법률 지식");
    await user.click(screen.getByRole("button", { name: "도메인 등록" }));

    const card = await screen.findByRole("article", { name: "법률 도메인" });
    expect(within(card).getByText("주소: legal")).toBeVisible();
    expect(within(card).queryByRole("textbox", { name: "도메인 주소" })).not.toBeInTheDocument();
    await user.clear(within(card).getByRole("textbox", { name: "표시 이름" }));
    await user.type(within(card).getByRole("textbox", { name: "표시 이름" }), "법률·준법");
    await user.clear(within(card).getByRole("textbox", { name: "설명" }));
    await user.type(within(card).getByRole("textbox", { name: "설명" }), "최신 설명");
    await user.click(within(card).getByRole("button", { name: "기본 정보 저장" }));

    expect(requests).toEqual([
      { path: "/api/v1/admin/rag/domains", body: { slug: "legal", display_name: "법률", description: "법률 지식" } },
      { path: "/api/v1/admin/rag/domains/domain-1", body: { display_name: "법률·준법", description: "최신 설명" } },
    ]);
  });

  it("creates an immutable connection with readable labels, then activates and deactivates it", async () => {
    const calls: string[] = [];
    let history = [connection({ id: "connection-1", version: 1 })];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      calls.push(`${init?.method ?? "GET"} ${path}`);
      if (path.endsWith("/connections") && init?.method === "POST") {
        history = [connection({ id: "connection-2", version: 2 }), ...history];
        return jsonResponse({ ...history[0], configuration_name: undefined, configuration_version: undefined }, 201);
      }
      if (path.endsWith("/connections")) return jsonResponse(history);
      if (path.endsWith("/activate")) return jsonResponse(adminDomain({ active_connection_version_id: "connection-2" }));
      if (path.endsWith("/deactivate")) return jsonResponse(adminDomain({ active_connection_version_id: null }));
      throw new Error(`Unexpected request: ${path}`);
    }));
    const user = userEvent.setup();
    render(
      <DomainAdminPage initialData={{
        domains: [listedDomain()],
        configurations: [configuration()],
        workspaces: [
          { id: "workspace-1", name: "회사 규정", kind: "company", expires_at: null },
          { id: "workspace-other", name: "범위 밖", kind: "team", expires_at: null },
        ],
        histories: { "domain-1": history },
      }} />,
    );

    const firstConnection = screen.getByRole("article", { name: "연결 버전 1" });
    expect(screen.getByText("활성")).toBeVisible();
    expect(within(firstConnection).getByText("현재 활성")).toBeVisible();
    expect(within(firstConnection).queryByRole("button", { name: "이 버전 활성화" })).not.toBeInTheDocument();
    expect(screen.queryByText(/configuration-version-1|workspace-1/)).not.toBeInTheDocument();
    await user.selectOptions(screen.getByRole("combobox", { name: "연결할 RAG 구성" }), "configuration-version-1");
    expect(screen.getByRole("option", { name: "승인된 금융 RAG · 버전 4" })).toBeVisible();
    expect(screen.getByRole("checkbox", { name: /회사 규정/ })).toBeVisible();
    expect(screen.queryByRole("checkbox", { name: /범위 밖/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: /회사 규정/ }));
    await user.click(screen.getByRole("button", { name: "새 연결 버전 만들기" }));

    const newest = await screen.findByRole("article", { name: "연결 버전 2" });
    expect(newest).toHaveTextContent("승인된 금융 RAG · 구성 버전 4");
    expect(newest).toHaveTextContent("회사 규정");
    expect(newest).not.toHaveTextContent(/connection-2|workspace-1|configuration-version-1/);
    await user.click(within(newest).getByRole("button", { name: "이 버전 활성화" }));
    expect(await within(newest).findByText("현재 활성")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "도메인 비활성화" }));
    expect(await within(newest).findByRole("button", { name: "이 버전 활성화" })).toBeVisible();
    expect(calls).toContain("POST /api/v1/admin/rag/domains/domain-1/connections");
    expect(calls).toContain("POST /api/v1/admin/rag/domains/domain-1/connections/connection-2/activate");
    expect(calls).toContain("POST /api/v1/admin/rag/domains/domain-1/deactivate");
  });

  it("keeps an inactive canonical domain inactive even when its latest history identity is present", () => {
    render(
      <DomainAdminPage initialData={{
        domains: [listedDomain({ active: false })],
        configurations: [],
        workspaces: [{ id: "workspace-1", name: "회사 규정", kind: "company", expires_at: null }],
        histories: { "domain-1": [connection()] },
      }} />,
    );

    const card = screen.getByRole("article", { name: "법률 도메인" });
    const historicalConnection = within(card).getByRole("article", { name: "연결 버전 1" });
    expect(within(card).getByText("비활성")).toBeVisible();
    expect(within(card).queryByRole("button", { name: "도메인 비활성화" })).not.toBeInTheDocument();
    expect(within(historicalConnection).getByRole("button", { name: "이 버전 활성화" })).toBeVisible();
  });
});

function listedDomain(overrides: Partial<Domain> = {}): Domain {
  return {
    id: "domain-1",
    slug: "legal",
    display_name: "법률",
    description: "법률 지식",
    active: true,
    ready: true,
    connection_version: { id: "connection-1", version: 1 },
    readiness: { search_ready: true, answer_ready: true, service_ready: true, reason_codes: [] },
    workspace_options: [{ id: "workspace-1", name: "회사 규정", kind: "company", expires_at: null }],
    generation_execution_preview: null,
    ...overrides,
  };
}

function adminDomain(overrides: Record<string, unknown> = {}) {
  return {
    id: "domain-1",
    slug: "legal",
    display_name: "법률",
    description: "법률 지식",
    active_connection_version_id: null,
    created_by: "owner-1",
    created_at: "2026-09-07T00:00:00Z",
    updated_at: "2026-09-07T00:00:00Z",
    ...overrides,
  };
}

function connection(overrides: Record<string, unknown> = {}) {
  return {
    id: "connection-1",
    domain_id: "domain-1",
    version: 1,
    configuration_version_id: "configuration-version-1",
    configuration_name: "승인된 금융 RAG",
    configuration_version: 4,
    workspace_ids: ["workspace-1"],
    created_by: "owner-1",
    created_at: "2026-09-07T00:00:00Z",
    ...overrides,
  };
}

function configuration(): SavedConfiguration {
  return {
    id: "configuration-1",
    version_id: "configuration-version-1",
    version: 4,
    name: "승인된 금융 RAG",
    workspace_ids: ["workspace-1"],
    answer_policy: { id: "answer-policy-1", version: 2, mode: "generative", conflict_mode: "separate_sources", min_keyword_coverage: 0.5, min_semantic_score: 0.5, require_complete_provenance: true },
    document_processing_profile_id: "processing-1",
    indexing_profile_id: "indexing-1",
    retrieval_profile_id: "retrieval-1",
    generation_profile_id: "generation-1",
    evaluation_state: "passed",
    experimental: false,
    is_default: false,
    is_system: false,
    owner_id: "owner-1",
    search_ready: true,
    search_reasons: [],
    answer_ready: true,
    answer_reasons: [],
    service_ready: true,
    generation_execution_preview: null,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
