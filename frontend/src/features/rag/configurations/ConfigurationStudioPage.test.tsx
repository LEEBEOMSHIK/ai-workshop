import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { ConfigurationStudioPage } from "./ConfigurationStudioPage";
import type { ConfigurationStudioData, SavedConfiguration } from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ConfigurationStudioPage", () => {
  it("shows only the automatic BM25 baseline before the user saves a configuration", () => {
    render(<ConfigurationStudioPage initialData={studioData()} />);

    const savedList = screen.getByRole("region", { name: "저장된 RAG 구성" });
    expect(within(savedList).getByText("BM25 기준선")).toBeVisible();
    expect(within(savedList).queryByText(/E5 하이브리드/)).not.toBeInTheDocument();
    expect(within(savedList).queryByText(/BGE 하이브리드/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "저장" })).toBeVisible();
    expect(screen.getByRole("button", { name: "저장하고 비교에 추가" })).toBeVisible();
  });

  it("warns that BGE needs a compatible new index and appends only the exact saved response", async () => {
    const saved = savedConfiguration({
      id: "configuration-bge",
      version_id: "configuration-bge-version-1",
      name: "내 BGE 구성",
      indexing_profile_id: "indexing-bge",
      retrieval_profile_id: "retrieval-bge",
      workspace_ids: ["workspace-company"],
    });
    let requestBody: unknown;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        if (input === "/api/v1/rag/configurations") {
          requestBody = JSON.parse(String(init?.body)) as unknown;
          return jsonResponse(saved, 201);
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    render(<ConfigurationStudioPage initialData={studioData()} />);

    await user.selectOptions(
      screen.getByRole("combobox", { name: "Embedding / Indexing Profile" }),
      "indexing-bge",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("호환되는 새 색인 버전");
    expect(screen.getByText("Dense").closest("p")).toHaveTextContent("bge-m3");

    await user.type(screen.getByRole("textbox", { name: "구성 이름" }), "내 BGE 구성");
    await user.click(screen.getByRole("checkbox", { name: /전사 지식/ }));
    await user.click(screen.getByRole("button", { name: "저장" }));

    expect(requestBody).toEqual({
      name: "내 BGE 구성",
      indexing_profile_id: "indexing-bge",
      retrieval_profile_id: "retrieval-bge",
      generation_profile_id: null,
      answer_policy: {
        min_semantic_score: 0.7,
        min_keyword_coverage: 0.5,
        require_complete_provenance: true,
        conflict_mode: "separate_sources",
      },
      workspace_ids: ["workspace-company"],
    });
    const savedList = screen.getByRole("region", { name: "저장된 RAG 구성" });
    expect(await within(savedList).findByText("내 BGE 구성")).toBeVisible();
    expect(within(savedList).getByText("configuration-bge-version-1")).toBeVisible();
    expect(within(savedList).queryByText("E5 하이브리드")).not.toBeInTheDocument();
  });

  it("registers the canonical three-tab studio route without removing the model registry", () => {
    render(<ConfigurationStudioPage initialData={studioData()} />);

    expect(screen.getByRole("tab", { name: "RAG 구성" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "비교 실험" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "모델 레지스트리" })).toBeVisible();
  });

  it("adds the exact saved version to comparison only through save-and-compare", async () => {
    const saved = savedConfiguration({
      id: "configuration-compare",
      version_id: "configuration-compare-version-1",
      name: "비교할 E5 구성",
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        if (input === "/api/v1/rag/configurations") return jsonResponse(saved, 201);
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );
    const user = userEvent.setup();
    render(<ConfigurationStudioPage initialData={studioData()} />);

    await user.type(screen.getByRole("textbox", { name: "구성 이름" }), "비교할 E5 구성");
    await user.click(screen.getByRole("checkbox", { name: /전사 지식/ }));
    await user.click(screen.getByRole("button", { name: "저장하고 비교에 추가" }));

    expect(await screen.findByRole("tab", { name: "비교 실험" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(
      screen.getByRole("checkbox", { name: /비교할 E5 구성.*configuration-compare-version-1/ }),
    ).toBeChecked();
  });

});

function studioData(): ConfigurationStudioData {
  return {
    configurations: [baselineConfiguration()],
    models: [
      {
        id: "model-e5",
        kind: "embedding",
        name: "multilingual-e5-base",
        version: 1,
        config: { repo_id: "intfloat/multilingual-e5-base", revision: "e5-revision" },
      },
      {
        id: "model-bge",
        kind: "embedding",
        name: "bge-m3",
        version: 1,
        config: { repo_id: "BAAI/bge-m3", revision: "bge-revision" },
      },
    ],
    profiles: [
      {
        id: "indexing-e5",
        kind: "indexing",
        name: "e5-structure-aware",
        version: 2,
        config: { parser: "structural-v1", chunker: "380/60" },
        bindings: [{ model_id: "model-e5", role: "embedding" }],
        evaluation_state: "draft",
        is_default: false,
      },
      {
        id: "indexing-bge",
        kind: "indexing",
        name: "bge-m3-structure-aware",
        version: 1,
        config: { parser: "structural-v1", chunker: "380/60" },
        bindings: [{ model_id: "model-bge", role: "embedding" }],
        evaluation_state: "draft",
        is_default: false,
      },
      {
        id: "retrieval-bm25",
        kind: "retrieval",
        name: "bm25-only",
        version: 1,
        config: { indexing_profile_id: "indexing-e5", bm25: {} },
        bindings: [],
        evaluation_state: "passed",
        is_default: true,
      },
      {
        id: "retrieval-e5",
        kind: "retrieval",
        name: "hybrid-e5-rrf",
        version: 1,
        config: { indexing_profile_id: "indexing-e5", bm25: {}, dense: {}, rrf: { k: 60 } },
        bindings: [],
        evaluation_state: "draft",
        is_default: false,
      },
      {
        id: "retrieval-bge",
        kind: "retrieval",
        name: "hybrid-bge-m3-rrf",
        version: 1,
        config: { indexing_profile_id: "indexing-bge", bm25: {}, dense: {}, rrf: { k: 60 } },
        bindings: [],
        evaluation_state: "draft",
        is_default: false,
      },
    ],
    workspaces: [
      { id: "workspace-company", name: "전사 지식", kind: "company", expires_at: null },
    ],
    runs: [],
  };
}

function baselineConfiguration(): SavedConfiguration {
  return savedConfiguration({
    id: "configuration-bm25",
    version_id: "configuration-bm25-version-1",
    name: "BM25 기준선",
    retrieval_profile_id: "retrieval-bm25",
    evaluation_state: "passed",
    is_default: true,
    is_system: true,
    experimental: false,
  });
}

function savedConfiguration(overrides: Partial<SavedConfiguration> = {}): SavedConfiguration {
  return {
    id: "configuration-1",
    version_id: "configuration-version-1",
    owner_id: "owner-1",
    name: "저장 구성",
    version: 1,
    indexing_profile_id: "indexing-e5",
    retrieval_profile_id: "retrieval-e5",
    generation_profile_id: null,
    answer_policy: {
      id: "answer-policy-1",
      version: 1,
      mode: "extractive",
      min_semantic_score: 0.7,
      min_keyword_coverage: 0.5,
      require_complete_provenance: true,
      conflict_mode: "separate_sources",
    },
    workspace_ids: ["workspace-company"],
    evaluation_state: "pending",
    is_system: false,
    is_default: false,
    experimental: true,
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}
