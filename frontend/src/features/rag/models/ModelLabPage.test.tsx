import { StrictMode } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { ModelLabPage } from "./ModelLabPage";
import type { ModelDefinitionSummary } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ModelLabPage", () => {
  it("loads owner-only Deployments and immutable data policies", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (input === "/api/v1/admin/rag/deployments") return jsonResponse([{
        deployment_id: "deployment-1",
        version_id: "deployment-version-1",
        version: 1,
        display_name: "사내 답변 모델",
        description: "사내 실행",
        model_name: "한국어 RAG LLM",
        model_version: 1,
        provider: "local_openai_compatible",
        provider_model_id: "local/korean-rag-v1",
        location: "on_premise",
        external_transfer: false,
        allowed_environments: ["development"],
        capabilities: ["structured_output", "contextualization"],
        secret_configured: false,
        readiness: { ready: true, reason_codes: [] },
        latest_health: null,
      }]);
      if (input === "/api/v1/admin/rag/data-policies/installation") return jsonResponse({
        policy_id: "installation",
        version_id: "installation-v1",
        version: 1,
        mode: "deny",
        approved_providers: [],
        changed_by: "owner",
        created_at: "2026-09-05T00:00:00Z",
      });
      if (input === "/api/v1/workspaces") return jsonResponse([{
        id: "workspace-1", name: "전사 지식", kind: "company", expires_at: null,
      }]);
      if (input === "/api/v1/admin/rag/data-policies/workspaces/workspace-1") return jsonResponse({
        policy_id: "workspace-policy",
        version_id: "workspace-policy-v1",
        workspace_id: "workspace-1",
        version: 1,
        mode: "inherit",
        approved_providers: [],
        changed_by: "owner",
        created_at: "2026-09-05T00:00:00Z",
      });
      throw new Error(`Unexpected request: ${String(input)}`);
    }));

    render(<ModelLabPage initialModels={[]} initialProfiles={[]} />);

    expect(screen.getByRole("status")).toHaveTextContent("실행 배포와 정책을 불러오는 중");
    expect(await screen.findByRole("heading", { name: "사내 답변 모델" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "외부 전송 정책" })).toBeVisible();
    expect(screen.getByText("전사 지식")).toBeVisible();
  });

  it("separates model and profile kinds without exposing execution controls", () => {
    render(
      <ModelLabPage
        initialModels={[
          {
            id: "embedding-1",
            kind: "embedding",
            name: "embedding-baseline",
            version: 1,
            config: { dimension: 768 },
          },
          {
            id: "llm-1",
            kind: "llm",
            name: "answer-model",
            version: 2,
            config: { endpoint_env: "LOCAL_LLM_ENDPOINT" },
          },
        ]}
        initialProfiles={[
          {
            id: "retrieval-1",
            kind: "retrieval",
            name: "hybrid-rrf",
            version: 1,
            config: { bm25: {}, dense: {}, rrf: {}, indexing_profile_id: "indexing-1" },
            bindings: [],
            deployment_version_id: null,
            legacy: false,
            readiness: { ready: false, reason_codes: [] },
            evaluation_state: "passed",
            is_default: true,
          },
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "임베딩 모델" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "리랭커 모델" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "LLM 모델" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "색인 프로파일" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "검색 프로파일" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "생성 프로파일" })).toBeVisible();
    expect(screen.getByText("embedding-baseline")).toBeVisible();
    expect(screen.getByText("hybrid-rrf")).toBeVisible();
    expect(screen.getByText("기본 사용")).toBeVisible();
    expect(screen.getByRole("button", { name: "모델 버전 등록" })).toBeVisible();
    expect(screen.getByRole("button", { name: "YAML 프로파일 등록" })).toBeVisible();
    expect(screen.queryByRole("button", { name: /실행/ })).not.toBeInTheDocument();
  });

  it("keeps model and profile identifiers behind closed technical details", async () => {
    const user = userEvent.setup();
    render(
      <ModelLabPage
        initialModels={[
          {
            id: "embedding-1",
            kind: "embedding",
            name: "embedding-baseline",
            version: 1,
            config: {
              repo_id: "local/embedding-baseline",
              revision: "revision-1",
              dimension: 768,
            },
          },
        ]}
        initialProfiles={[
          {
            id: "retrieval-1",
            kind: "retrieval",
            name: "hybrid-rrf",
            version: 2,
            config: { bm25: {}, dense: {}, rrf: {}, indexing_profile_id: "indexing-1" },
            bindings: [{ model_id: "embedding-1", role: "embedding" }],
            deployment_version_id: null,
            legacy: false,
            readiness: { ready: false, reason_codes: [] },
            evaluation_state: "passed",
            is_default: true,
          },
        ]}
      />,
    );

    const modelRow = screen.getByText("embedding-baseline").closest("tr");
    const profileRow = screen.getByText("hybrid-rrf").closest("tr");
    expect(modelRow).not.toBeNull();
    expect(profileRow).not.toBeNull();
    expect(within(modelRow!).getByText("v1")).toBeVisible();
    expect(within(profileRow!).getByText("v2")).toBeVisible();

    const modelSummary = within(modelRow!).getByText("기술 식별자 보기");
    const profileSummary = within(profileRow!).getByText("기술 식별자 보기");
    const modelDetails = modelSummary.closest("details");
    const profileDetails = profileSummary.closest("details");
    expect(modelDetails).not.toBeNull();
    expect(profileDetails).not.toBeNull();
    expect(modelDetails).not.toHaveAttribute("open");
    expect(profileDetails).not.toHaveAttribute("open");
    expect(within(modelDetails!).getByText("embedding-1", { exact: true })).not.toBeVisible();
    expect(within(profileDetails!).getByText("retrieval-1", { exact: true })).not.toBeVisible();

    await user.click(modelSummary);
    await user.click(profileSummary);

    expect(modelDetails).toHaveAttribute("open");
    expect(profileDetails).toHaveAttribute("open");
    expect(within(modelDetails!).getByText("embedding-1", { exact: true })).toBeVisible();
    expect(within(profileDetails!).getByText("retrieval-1", { exact: true })).toBeVisible();
  });

  it("preserves model and YAML profile registration while excluding BM25 and RRF model rows", async () => {
    const modelResponse = {
      id: "embedding-registered",
      kind: "embedding" as const,
      name: "registered-embedding",
      version: 4,
      config: { repo_id: "local/embedding", revision: "revision-4" },
    };
    const profileResponse = {
      id: "retrieval-registered",
      kind: "retrieval" as const,
      name: "registered-retrieval",
      version: 2,
      config: { indexing_profile_id: "indexing-1", bm25: {}, dense: {}, rrf: {} },
      bindings: [],
      deployment_version_id: null,
      legacy: false,
      readiness: { ready: false, reason_codes: [] },
      evaluation_state: "draft" as const,
      is_default: false,
    };
    const requests: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        requests.push([input, init]);
        if (input === "/api/v1/admin/rag/models") return jsonResponse(modelResponse, 201);
        if (input === "/api/v1/admin/rag/profiles/retrieval/yaml") {
          return jsonResponse(profileResponse, 201);
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );
    const retrievalMethods = [
      { id: "not-model-bm25", kind: "bm25", name: "BM25", version: 1, config: {} },
      { id: "not-model-rrf", kind: "rrf", name: "RRF", version: 1, config: {} },
    ] as unknown as ModelDefinitionSummary[];

    const user = userEvent.setup();
    render(<ModelLabPage initialModels={retrievalMethods} initialProfiles={[]} />);

    expect(screen.queryByText("BM25")).not.toBeInTheDocument();
    expect(screen.queryByText("RRF")).not.toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "이름" }), "registered-embedding");
    await user.clear(screen.getByRole("spinbutton", { name: "버전" }));
    await user.type(screen.getByRole("spinbutton", { name: "버전" }), "4");
    fireEvent.change(screen.getByRole("textbox", { name: "설정 JSON" }), {
      target: { value: JSON.stringify(modelResponse.config) },
    });
    await user.click(screen.getByRole("button", { name: "모델 버전 등록" }));
    expect(await screen.findByText("registered-embedding")).toBeVisible();

    const profileForm = screen.getByRole("heading", { name: "새 프로파일 버전" }).closest("form");
    expect(profileForm).not.toBeNull();
    await user.selectOptions(within(profileForm!).getByRole("combobox", { name: "종류" }), "retrieval");
    fireEvent.change(within(profileForm!).getByRole("textbox", { name: "프로파일 YAML" }), {
      target: {
        value: "kind: retrieval\nname: registered-retrieval\nversion: 2\nconfig:\n  bm25: {}\nbindings: []",
      },
    });
    await user.click(within(profileForm!).getByRole("button", { name: "YAML 프로파일 등록" }));
    expect(await screen.findByText("registered-retrieval")).toBeVisible();
    expect(requests.map(([input]) => input).filter((input) =>
      String(input).includes("/admin/rag/models") || String(input).includes("/profiles/"),
    )).toEqual([
      "/api/v1/admin/rag/models",
      "/api/v1/admin/rag/profiles/retrieval/yaml",
    ]);
  });

  it("releases both async registration controls and applies responses under StrictMode", async () => {
    const modelRequest = deferred<Response>();
    const profileRequest = deferred<Response>();
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL) => {
        if (input === "/api/v1/admin/rag/models") return modelRequest.promise;
        if (input === "/api/v1/admin/rag/profiles/retrieval/yaml") return profileRequest.promise;
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    render(
      <StrictMode>
        <ModelLabPage initialModels={[]} initialProfiles={[]} />
      </StrictMode>,
    );

    await user.type(screen.getByRole("textbox", { name: "이름" }), "strict-embedding");
    await user.click(screen.getByRole("button", { name: "모델 버전 등록" }));
    expect(screen.getByRole("button", { name: "등록 중…" })).toBeDisabled();
    modelRequest.resolve(jsonResponse({
      id: "strict-model-id",
      kind: "embedding",
      name: "strict-embedding",
      version: 1,
      config: {},
    }, 201));
    expect(await screen.findByText("strict-embedding")).toBeVisible();
    expect(screen.getByRole("button", { name: "모델 버전 등록" })).toBeEnabled();

    const profileForm = screen.getByRole("heading", { name: "새 프로파일 버전" }).closest("form");
    expect(profileForm).not.toBeNull();
    await user.click(within(profileForm!).getByRole("button", { name: "YAML 프로파일 등록" }));
    expect(within(profileForm!).getByRole("button", { name: "등록 중…" })).toBeDisabled();
    profileRequest.resolve(jsonResponse({
      id: "strict-profile-id",
      kind: "retrieval",
      name: "strict-retrieval",
      version: 1,
      config: { indexing_profile_id: "indexing-1", bm25: {}, dense: {}, rrf: {} },
      bindings: [],
      deployment_version_id: null,
      legacy: false,
      readiness: { ready: false, reason_codes: [] },
      evaluation_state: "draft",
      is_default: false,
    }, 201));
    expect(await screen.findByText("strict-retrieval")).toBeVisible();
    expect(within(profileForm!).getByRole("button", { name: "YAML 프로파일 등록" })).toBeEnabled();
  });
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}
