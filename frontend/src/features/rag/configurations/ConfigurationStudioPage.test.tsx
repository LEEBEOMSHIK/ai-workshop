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

    const indexingSelect = screen.getByRole("combobox", {
      name: "색인 패키지",
    });
    const retrievalSelect = screen.getByRole("combobox", {
      name: "Retrieval Profile",
    });
    expect(indexingSelect).toHaveValue("indexing-e5");
    expect(
      within(indexingSelect).queryByRole("option", { name: /indexing-e5/ }),
    ).not.toBeInTheDocument();
    expect(
      within(retrievalSelect).getByRole("option", { name: "hybrid-e5-rrf v1" }),
    ).toHaveValue("retrieval-e5");
    expect(
      within(retrievalSelect).queryByRole("option", { name: /retrieval-e5/ }),
    ).not.toBeInTheDocument();
    expect(
      within(retrievalSelect).queryByRole("option", { name: "지원하지 않는 리랭커 v1" }),
    ).not.toBeInTheDocument();
    const builder = screen.getByRole("heading", { name: "새 RAG 패키지 구성" }).closest("section");
    expect(builder).not.toBeNull();
    if (!builder) throw new Error("Expected the configuration builder.");
    const embedding = within(builder).getByText("Embedding").closest("p");
    expect(embedding).toHaveTextContent("multilingual-e5-base v1");
    expect(embedding).not.toHaveTextContent("model-e5");
    expect(screen.getByRole("checkbox", { name: "전사 지식" })).toHaveAttribute(
      "value",
      "workspace-company",
    );

    const savedList = screen.getByRole("region", { name: "저장된 RAG 구성" });
    expect(within(savedList).getByText("BM25 기준선")).toBeVisible();
    expect(within(savedList).queryByText(/E5 하이브리드/)).not.toBeInTheDocument();
    expect(within(savedList).queryByText(/BGE 하이브리드/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "저장" })).toBeVisible();
    expect(screen.getByRole("button", { name: "저장하고 비교에 추가" })).toBeVisible();
  });

  it("describes indexing choices by embedding and chunker roles without internal identifiers", () => {
    render(<ConfigurationStudioPage initialData={studioData()} />);

    const indexingSelect = screen.getByRole("combobox", {
      name: "색인 패키지",
    });
    expect(
      within(indexingSelect).getByRole("option", {
        name: "임베딩: multilingual-e5-base v1 · 청킹: structure-aware v2 / 목표 380 / 중첩 60 · 프로파일 v2",
      }),
    ).toHaveValue("indexing-e5");
    expect(
      within(indexingSelect).getByRole("option", {
        name: "임베딩: bge-m3 v1 · 청킹: semantic-window v1 / 목표 512 / 중첩 96 · 프로파일 v1",
      }),
    ).toHaveValue("indexing-bge");
    expect(
      within(indexingSelect).queryByRole("option", {
        name: /indexing-e5|indexing-bge|e5-structure-aware|bge-m3-structure-aware/,
      }),
    ).not.toBeInTheDocument();
  });

  it("excludes indexing profiles that have no embedding binding", () => {
    const data = studioData();
    data.profiles = [
      {
        id: "indexing-without-embedding",
        kind: "indexing",
        name: "unbound-indexing-profile",
        version: 1,
        config: {
          chunker: {
            name: "structure-aware",
            version: 2,
            target_tokens: 380,
            overlap_tokens: 60,
          },
        },
        bindings: [],
        evaluation_state: "draft",
        is_default: false,
      },
      ...data.profiles,
    ];
    render(<ConfigurationStudioPage initialData={data} />);

    const indexingSelect = screen.getByRole("combobox", {
      name: "색인 패키지",
    }) as HTMLSelectElement;
    expect(Array.from(indexingSelect.options, (option) => option.value)).not.toContain(
      "indexing-without-embedding",
    );
    expect(
      within(indexingSelect).queryByRole("option", { name: /unbound-indexing-profile/ }),
    ).not.toBeInTheDocument();
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
      screen.getByRole("combobox", { name: "색인 패키지" }),
      "indexing-bge",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("호환되는 새 색인 버전");
    const builder = screen.getByRole("region", { name: "새 RAG 패키지 구성" });
    expect(within(builder).getByText("Dense Retriever").closest("p")).toHaveTextContent("bge-m3");

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
    expect(within(savedList).queryByText("E5 하이브리드")).not.toBeInTheDocument();
  });

  it("reveals saved configuration identifiers only through technical details", async () => {
    const user = userEvent.setup();
    render(<ConfigurationStudioPage initialData={studioData()} />);

    const heading = screen.getByRole("heading", { name: "BM25 기준선" });
    const card = heading.closest("article");
    expect(card).not.toBeNull();
    if (!card) throw new Error("Expected a saved configuration card.");

    expect(within(card).getByText("e5-structure-aware v2")).toBeVisible();
    expect(within(card).getByText("multilingual-e5-base v1")).toBeVisible();
    expect(within(card).getByText("bm25-only v1")).toBeVisible();

    const summary = within(card).getByText("기술 식별자 보기");
    const details = summary.closest("details");
    expect(details).not.toBeNull();
    if (!details) throw new Error("Expected technical identifier details.");
    expect(details).not.toHaveAttribute("open");

    const identifiers = [
      "configuration-bm25",
      "configuration-bm25-version-1",
      "indexing-e5",
      "model-e5",
      "retrieval-bm25",
      "answer-policy-1",
      "workspace-company",
    ];
    for (const identifier of identifiers) {
      expect(within(details).getByText(identifier, { exact: true })).not.toBeVisible();
    }

    await user.click(summary);

    expect(details).toHaveAttribute("open");
    for (const identifier of identifiers) {
      expect(within(details).getByText(identifier, { exact: true })).toBeVisible();
    }
  });

  it("shows every saved RAG package component with human-readable identities", () => {
    const data = studioData();
    data.configurations = [savedConfiguration({ name: "내 E5 패키지" })];
    render(<ConfigurationStudioPage initialData={data} />);

    const heading = screen.getByRole("heading", { name: "내 E5 패키지" });
    const card = heading.closest("article");
    expect(card).not.toBeNull();
    if (!card) throw new Error("Expected a saved RAG package card.");

    const expectedComponents = [
      ["Parser", "형식별 자동 선택 · 현재 구성에 고정되지 않음"],
      ["Chunker", "structure-aware · v2 · target 380 · overlap 60"],
      ["Embedding", "multilingual-e5-base v1"],
      ["Sparse Retriever", "BM25"],
      ["Dense Retriever", "Bi-encoder · multilingual-e5-base v1"],
      ["Fusion", "RRF (k=60)"],
      ["Reranker", "사용 안 함 (V1)"],
      ["Answer Policy", "extractive v1"],
      ["LLM", "사용 안 함 (V1)"],
    ] as const;

    for (const [label, value] of expectedComponents) {
      const definition = within(card).getByText(label, { selector: "dt", exact: true });
      expect(definition.closest("div")).toHaveTextContent(value);
    }

    const technicalDetails = within(card).getByText("기술 식별자 보기").closest("details");
    expect(technicalDetails).not.toBeNull();
    expect(technicalDetails).not.toHaveAttribute("open");
    for (const identifier of [
      "configuration-1",
      "configuration-version-1",
      "indexing-e5",
      "model-e5",
      "retrieval-e5",
      "answer-policy-1",
      "workspace-company",
    ]) {
      expect(within(technicalDetails!).getByText(identifier, { exact: true })).not.toBeVisible();
    }
  });

  it("keeps the model registry read-only inside the user configuration studio", async () => {
    const user = userEvent.setup();
    render(<ConfigurationStudioPage initialData={studioData()} />);

    expect(screen.getByRole("tab", { name: "RAG 구성" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "비교 실험" })).toBeVisible();
    expect(screen.getByRole("tab", { name: "모델 레지스트리" })).toBeVisible();
    await user.click(screen.getByRole("tab", { name: "모델 레지스트리" }));
    expect(screen.getByText("multilingual-e5-base")).toBeVisible();
    expect(screen.queryByRole("button", { name: "모델 버전 등록" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "YAML 프로파일 등록" })).not.toBeInTheDocument();
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
      screen.getByRole("checkbox", { name: "비교할 E5 구성 v1" }),
    ).toBeChecked();
    expect(screen.queryByText("configuration-compare-version-1")).not.toBeInTheDocument();
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
        config: {
          chunker: {
            name: "structure-aware",
            version: 2,
            target_tokens: 380,
            overlap_tokens: 60,
          },
        },
        bindings: [{ model_id: "model-e5", role: "embedding" }],
        evaluation_state: "draft",
        is_default: false,
      },
      {
        id: "indexing-bge",
        kind: "indexing",
        name: "bge-m3-structure-aware",
        version: 1,
        config: {
          parser: "structural-v1",
          chunker: {
            name: "semantic-window",
            version: 1,
            target_tokens: 512,
            overlap_tokens: 96,
          },
        },
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
        config: {
          indexing_profile_id: "indexing-e5",
          bm25: {},
          dense: {},
          rrf: { k: 60 },
          reranker: null,
        },
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
      {
        id: "retrieval-reranker-enabled",
        kind: "retrieval",
        name: "지원하지 않는 리랭커",
        version: 1,
        config: {
          indexing_profile_id: "indexing-e5",
          bm25: {},
          dense: {},
          rrf: { k: 60 },
          reranker: { enabled: true },
        },
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
    search_ready: true,
    ...overrides,
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}
