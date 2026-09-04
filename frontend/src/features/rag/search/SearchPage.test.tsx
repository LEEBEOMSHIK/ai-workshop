import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import type { DeploymentOption, GenerationProfile, SavedConfiguration } from "./api";
import { SearchPage } from "./SearchPage";

function MemoryRouter({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SearchPage", () => {
  it("keeps a ready extractive search usable when optional generation metadata fails", async () => {
    const extractive = savedConfiguration({
      generation_profile_id: null,
      answer_policy: { ...savedConfiguration().answer_policy, mode: "extractive" },
    });
    let submitted = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (input === "/api/v1/workspaces") {
        return jsonResponse([{ id: "company-1", name: "전사 규정", kind: "company", expires_at: null }]);
      }
      if (input === "/api/v1/rag/configurations") return jsonResponse([extractive]);
      if (input === "/api/v1/rag/profiles/generation" || input === "/api/v1/rag/deployments/options") {
        return jsonResponse({ error: { code: "request_failed", message: "raw metadata raw", correlation_id: "c" } }, 503);
      }
      if (input === "/api/v1/workspaces/company-1/folders") return jsonResponse([]);
      if (input === "/api/v1/rag/search") {
        submitted = true;
        return jsonResponse({
          status: "insufficient_evidence",
          answer: null,
          conflict_state: "none",
          conflicts: [],
          warnings: [],
          related_sources: [],
          configuration_version: { configuration_id: "configuration-1", version_id: "version-1", version: 3 },
          experimental: false,
          resolved_query: "추출식 질문",
          generation: {
            execution: null,
            status: "not_requested",
            text: null,
            citations: [],
            reason_codes: [],
            turn_id: null,
            validation_token: null,
          },
        });
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    }));
    const user = userEvent.setup();
    render(<MemoryRouter><SearchPage /></MemoryRouter>);

    await user.click(await screen.findByRole("checkbox", { name: /전사 규정/ }));
    await user.selectOptions(screen.getByRole("combobox", { name: "저장된 RAG 구성" }), "configuration-1");
    await user.type(screen.getByRole("searchbox", { name: "검색 질문" }), "추출식 질문");
    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));

    expect(submitted).toBe(true);
    expect(screen.queryByText("raw metadata raw")).not.toBeInTheDocument();
  });

  it.each([
    ["exact generation Profile", [], [deploymentOption()]],
    ["exact Deployment", [generationProfile("generation-1", "deployment-missing")], [deploymentOption()]],
  ])("blocks only a generative submit when the %s join is missing", async (_caseName, generationProfiles, deployments) => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SearchPage initialOptions={{
          configurations: [savedConfiguration()],
          workspaces: [{ id: "company-1", name: "전사 규정", kind: "company", expires_at: null }],
          generationProfiles,
          deployments,
        }} />
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("checkbox", { name: /전사 규정/ }));
    await user.selectOptions(screen.getByRole("combobox", { name: "저장된 RAG 구성" }), "configuration-1");
    await user.type(screen.getByRole("searchbox", { name: "검색 질문" }), "생성 질문");

    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
    expect(screen.getByRole("status", { name: "선택한 구성 처리 안내" })).toHaveTextContent(
      "선택한 구성의 모델 및 처리 위치를 확인할 수 없습니다.",
    );
  });

  it.each([
    ["Deployment", true],
    ["generation Profile", false],
  ])("loads only the missing %s without replacing supplied metadata", async (_missing, profilesSupplied) => {
    const suppliedProfile = generationProfile("generation-1", "deployment-external");
    const suppliedDeployment = deploymentOption();
    const requests: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      requests.push(String(input));
      if (input === "/api/v1/rag/profiles/generation") return jsonResponse([suppliedProfile]);
      if (input === "/api/v1/rag/deployments/options") return jsonResponse([suppliedDeployment]);
      throw new Error(`Unexpected request: ${String(input)}`);
    }));
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SearchPage initialOptions={{
          configurations: [savedConfiguration()],
          workspaces: [],
          ...(profilesSupplied
            ? { generationProfiles: [suppliedProfile] }
            : { deployments: [suppliedDeployment] }),
        }} />
      </MemoryRouter>,
    );

    await user.selectOptions(screen.getByRole("combobox", { name: "저장된 RAG 구성" }), "configuration-1");
    expect(await screen.findByText(
      "현재 질문, 제한된 이전 대화와 선별된 문서 근거가 OpenAI 외부 API로 전송됩니다.",
    )).toBeVisible();
    expect(requests).toEqual([
      profilesSupplied ? "/api/v1/rag/deployments/options" : "/api/v1/rag/profiles/generation",
    ]);
  });

  it("updates the server disclosure and keyboard-accessible processing details with the selected configuration", async () => {
    const externalConfiguration = savedConfiguration({
      id: "configuration-external",
      name: "외부 생성 구성",
      generation_profile_id: "generation-external",
    });
    const localConfiguration = savedConfiguration({
      id: "configuration-local",
      name: "사내 생성 구성",
      generation_profile_id: "generation-local",
    });
    const externalDeployment = deploymentOption();
    Reflect.set(externalDeployment, "secret_ref", "sk-not-a-real-secret");
    Reflect.set(externalDeployment, "endpoint_ref", "endpoint-ref");
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SearchPage
          initialOptions={{
            configurations: [externalConfiguration, localConfiguration],
            workspaces: [
              { id: "company-1", name: "전사 규정", kind: "company", expires_at: null },
            ],
            generationProfiles: [
              generationProfile("generation-external", "deployment-external"),
              generationProfile("generation-local", "deployment-local"),
            ],
            deployments: [
              externalDeployment,
              deploymentOption({
                deployment_version_id: "deployment-local",
                display_name: "사내 금융 답변",
                model_name: "사내 Korean LLM",
                model_version: 4,
                provider: "local_openai_compatible",
                provider_model_id: "internal/korean-rag-v4",
                location: "on_premise",
                external_transfer: false,
                approval: {
                  required: false,
                  disclosure_version: "on-premise-generation-v1",
                  disclosure: "질문과 근거는 승인된 사내 환경에서만 처리됩니다.",
                  transmitted_data_categories: [],
                },
              }),
            ],
          }}
        />
      </MemoryRouter>,
    );

    const configuration = screen.getByRole("combobox", { name: "저장된 RAG 구성" });
    await user.selectOptions(configuration, "configuration-external");
    expect(screen.getByRole("status", { name: "선택한 구성 처리 안내" })).toHaveTextContent(
      "현재 질문, 제한된 이전 대화와 선별된 문서 근거가 OpenAI 외부 API로 전송됩니다.",
    );
    const detailsButton = screen.getByRole("button", { name: "모델 및 처리 위치 상세" });
    detailsButton.focus();
    await user.keyboard("{Enter}");
    const details = screen.getByRole("region", { name: "모델 및 처리 위치 상세" });
    expect(details).toHaveTextContent("OpenAI GPT-5 mini v2");
    expect(details).toHaveTextContent("OpenAI Responses API");
    expect(details).toHaveTextContent("외부 API");
    expect(details).toHaveTextContent("외부 전송 대상");
    expect(details).not.toHaveTextContent(/deployment-external|sk-not-a-real-secret|endpoint-ref/);

    await user.selectOptions(configuration, "configuration-local");
    expect(screen.getByRole("status", { name: "선택한 구성 처리 안내" })).toHaveTextContent(
      "질문과 근거는 승인된 사내 환경에서만 처리됩니다.",
    );
    expect(screen.queryByText(/OpenAI 외부 API로 전송/)).not.toBeInTheDocument();
  });

  it("explains an extractive configuration without inventing a provider execution", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SearchPage
          initialOptions={{
            configurations: [savedConfiguration({
              generation_profile_id: null,
              answer_policy: { ...savedConfiguration().answer_policy, mode: "extractive" },
            })],
            workspaces: [],
            generationProfiles: [],
            deployments: [],
          }}
        />
      </MemoryRouter>,
    );

    await user.selectOptions(
      screen.getByRole("combobox", { name: "저장된 RAG 구성" }),
      "configuration-1",
    );
    expect(screen.getByRole("status", { name: "선택한 구성 처리 안내" })).toHaveTextContent(
      "LLM 생성을 요청하지 않는 추출식 구성입니다.",
    );
    expect(screen.queryByRole("button", { name: "모델 및 처리 위치 상세" })).not.toBeInTheDocument();
  });

  it("sends signed prior turns for a contextual follow-up and keeps both turns visible", async () => {
    const searchBodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const metadata = processingMetadataResponse(input);
        if (metadata) return metadata;
        if (input === "/api/v1/workspaces") {
          return jsonResponse([
            { id: "company-1", name: "전사 규정", kind: "company", expires_at: null },
          ]);
        }
        if (input === "/api/v1/rag/configurations") {
          return jsonResponse([savedConfiguration()]);
        }
        if (input === "/api/v1/workspaces/company-1/folders") return jsonResponse([]);
        if (input === "/api/v1/rag/search") {
          const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
          searchBodies.push(body);
          const first = searchBodies.length === 1;
          return jsonResponse({
            status: "supported",
            answer: evidenceAnswer(),
            conflict_state: "none",
            conflicts: [],
            warnings: [],
            related_sources: [],
            configuration_version: {
              configuration_id: "configuration-1",
              version_id: "configuration-version-1",
              version: 3,
            },
            experimental: false,
            resolved_query: first ? "위험 한도" : "위험 한도 7% 적용일",
            generation: {
              status: "answered",
              text: first
                ? "위험 한도는 순자산의 7%입니다."
                : "적용일은 2026-09-01입니다.",
              citations: [{ claim_index: 0, evidence_ids: ["evidence-1"] }],
              reason_codes: [],
              turn_id: first ? "turn-1" : "turn-2",
              validation_token: first ? "signed-turn-1" : "signed-turn-2",
            },
          });
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("checkbox", { name: /전사 규정/ }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "저장된 RAG 구성" }),
      "configuration-1",
    );
    const query = screen.getByRole("searchbox", { name: "검색 질문" });
    await user.type(query, "위험 한도는 얼마야?");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    expect(await screen.findByText("위험 한도는 순자산의 7%입니다.")).toBeVisible();

    await user.type(query, "그건 언제부터야?");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));

    expect(await screen.findByText("적용일은 2026-09-01입니다.")).toBeVisible();
    expect(screen.getByText("위험 한도는 얼마야?")).toBeVisible();
    expect(screen.getByText("그건 언제부터야?")).toBeVisible();
    expect(screen.getByText("검색에 사용한 질의: 위험 한도 7% 적용일")).toBeVisible();
    expect(searchBodies[0]).toMatchObject({ history: [] });
    expect(searchBodies[1]).toMatchObject({
      history: [
        { role: "user", content: "위험 한도는 얼마야?" },
        {
          role: "assistant",
          content: "위험 한도는 순자산의 7%입니다.",
          turn_id: "turn-1",
          validation_token: "signed-turn-1",
        },
      ],
    });
  });

  it("sends only the newest 20 completed conversation turns", async () => {
    const searchBodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const metadata = processingMetadataResponse(input);
        if (metadata) return metadata;
        if (input === "/api/v1/workspaces/company-1/folders") return jsonResponse([]);
        if (input === "/api/v1/rag/search") {
          const body = JSON.parse(String(init?.body)) as Record<string, unknown>;
          searchBodies.push(body);
          const turn = searchBodies.length;
          return jsonResponse({
            status: "supported",
            answer: evidenceAnswer(),
            conflict_state: "none",
            conflicts: [],
            warnings: [],
            related_sources: [],
            configuration_version: {
              configuration_id: "configuration-1",
              version_id: "configuration-version-1",
              version: 3,
            },
            experimental: false,
            resolved_query: `질문 ${turn}`,
            generation: {
              status: "answered",
              text: `답변 ${turn}`,
              citations: [{ claim_index: 0, evidence_ids: ["evidence-1"] }],
              reason_codes: [],
              turn_id: `turn-${turn}`,
              validation_token: `signed-turn-${turn}`,
            },
          });
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SearchPage
          initialOptions={{
            configurations: [savedConfiguration()],
            workspaces: [
              { id: "company-1", name: "전사 규정", kind: "company", expires_at: null },
            ],
          }}
        />
      </MemoryRouter>,
    );

    await user.click(screen.getByRole("checkbox", { name: /전사 규정/ }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "저장된 RAG 구성" }),
      "configuration-1",
    );
    const query = screen.getByRole("searchbox", { name: "검색 질문" });
    for (let turn = 1; turn <= 12; turn += 1) {
      await user.type(query, `질문 ${turn}`);
      await user.click(screen.getByRole("button", { name: "질문 보내기" }));
      await waitFor(() => expect(query).toHaveValue(""));
    }

    const lastHistory = searchBodies[11].history as Array<{
      role: string;
      content: string;
    }>;
    expect(lastHistory).toHaveLength(20);
    expect(lastHistory.map(({ role, content }) => `${role}:${content}`)).toEqual([
      "user:질문 2",
      "assistant:답변 2",
      "user:질문 3",
      "assistant:답변 3",
      "user:질문 4",
      "assistant:답변 4",
      "user:질문 5",
      "assistant:답변 5",
      "user:질문 6",
      "assistant:답변 6",
      "user:질문 7",
      "assistant:답변 7",
      "user:질문 8",
      "assistant:답변 8",
      "user:질문 9",
      "assistant:답변 9",
      "user:질문 10",
      "assistant:답변 10",
      "user:질문 11",
      "assistant:답변 11",
    ]);
  }, 15_000);

  it("searches only explicitly selected workspaces and places confirmed evidence before related documents", async () => {
    const requests: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const metadata = processingMetadataResponse(input);
        if (metadata) return metadata;
        requests.push([input, init]);
        if (input === "/api/v1/workspaces") {
          return jsonResponse([
            { id: "company-1", name: "전사 규정", kind: "company", expires_at: null },
            { id: "personal-1", name: "개인 리서치", kind: "personal", expires_at: null },
            { id: "temporary-1", name: "임시 검토", kind: "temporary", expires_at: null },
          ]);
        }
        if (input === "/api/v1/rag/configurations") {
          return jsonResponse([savedConfiguration()]);
        }
        if (input === "/api/v1/workspaces/company-1/folders") return jsonResponse([]);
        if (input === "/api/v1/workspaces/personal-1/folders") return jsonResponse([]);
        if (input === "/api/v1/rag/search") {
          return jsonResponse({
            status: "supported",
            answer: evidenceAnswer(),
            conflict_state: "none",
            conflicts: [],
            warnings: [],
            related_sources: [
              {
                document_id: "document-2",
                asset_version_id: "asset-version-2",
                asset_version_number: 2,
                workspace_id: "personal-1",
                folder_id: null,
                projection_id: "projection-2",
                chunk_id: "chunk-2",
                title: "후속 검토.md",
                media_type: "text/markdown",
                section_path: ["위험 요인"],
                fused_score: 0.43,
              },
            ],
            configuration_version: {
              configuration_id: "configuration-1",
              version_id: "configuration-version-1",
              version: 3,
            },
            experimental: false,
          });
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("checkbox", { name: /전사 규정/ }));
    await user.click(screen.getByRole("checkbox", { name: /개인 리서치/ }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "저장된 RAG 구성" }),
      "configuration-1",
    );
    await user.type(screen.getByRole("searchbox", { name: "검색 질문" }), "환매 제한은 무엇인가요?");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));

    const evidenceHeading = await screen.findByRole("heading", { name: "확인된 근거" });
    const relatedHeading = screen.getByRole("heading", { name: "관련 문서" });
    expect(
      evidenceHeading.compareDocumentPosition(relatedHeading),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(screen.getByText("환매 요청은 영업일 기준 3일 전에 접수해야 합니다.")).toBeVisible();
    expect(screen.getByText("후속 검토.md")).toBeVisible();

    const searchRequest = requests.find(([input]) => input === "/api/v1/rag/search");
    expect(searchRequest?.[1]).toMatchObject({
      method: "POST",
      credentials: "include",
      body: JSON.stringify({
        query: "환매 제한은 무엇인가요?",
        configuration_id: "configuration-1",
        workspace_ids: ["company-1", "personal-1"],
        folder_ids: [],
        top_k: 10,
        experimental: false,
        history: [],
      }),
    });
    expect(JSON.parse(String(searchRequest?.[1]?.body))).not.toHaveProperty("user_id");
  });

  it("requires separate consent for an experimental configuration before sending experimental true", async () => {
    let searchBody: Record<string, unknown> | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const metadata = processingMetadataResponse(input);
        if (metadata) return metadata;
        if (input === "/api/v1/workspaces") {
          return jsonResponse([
            { id: "company-1", name: "전사 규정", kind: "company", expires_at: null },
          ]);
        }
        if (input === "/api/v1/rag/configurations") {
          return jsonResponse([
            savedConfiguration({
              evaluation_state: "pending",
              experimental: true,
              is_default: false,
              name: "평가 대기 구성",
            }),
          ]);
        }
        if (input === "/api/v1/rag/search") {
          searchBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
          return jsonResponse({
            status: "insufficient_evidence",
            answer: null,
            conflict_state: "none",
            conflicts: [],
            warnings: [],
            related_sources: [
              {
                document_id: "document-2",
                asset_version_id: "asset-version-2",
                asset_version_number: 1,
                workspace_id: "company-1",
                folder_id: null,
                projection_id: "projection-2",
                chunk_id: "chunk-2",
                title: "참고 문서.md",
                media_type: "text/markdown",
                section_path: ["참고"],
                fused_score: 0.3,
              },
            ],
            configuration_version: {
              configuration_id: "configuration-1",
              version_id: "configuration-version-1",
              version: 3,
            },
            experimental: true,
          });
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("checkbox", { name: /전사 규정/ }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "저장된 RAG 구성" }),
      "configuration-1",
    );
    await user.type(screen.getByRole("searchbox", { name: "검색 질문" }), "근거가 있나요?");

    expect(screen.getByText("실험")).toBeVisible();
    const submit = screen.getByRole("button", { name: "질문 보내기" });
    expect(submit).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "평가 전 구성을 실험 검색에 사용" }));
    expect(submit).toBeEnabled();
    await user.click(submit);

    expect(searchBody).toMatchObject({
      configuration_id: "configuration-1",
      experimental: true,
      workspace_ids: ["company-1"],
    });
    const insufficient = (await screen.findByText("직접 답할 근거가 부족합니다")).closest("[role=status]")!;
    const related = screen.getByRole("heading", { name: "관련 문서" });
    expect(insufficient).toHaveTextContent("직접 답할 근거가 부족합니다");
    expect(insufficient.compareDocumentPosition(related)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(screen.queryByRole("heading", { name: "확인된 근거" })).not.toBeInTheDocument();
    expect(screen.getByText("참고 문서.md")).toBeVisible();
  });

  it("sends only folders explicitly selected inside a selected workspace", async () => {
    let searchBody: Record<string, unknown> | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const metadata = processingMetadataResponse(input);
        if (metadata) return metadata;
        if (input === "/api/v1/workspaces") {
          return jsonResponse([
            { id: "company-1", name: "전사 규정", kind: "company", expires_at: null },
          ]);
        }
        if (input === "/api/v1/rag/configurations") {
          return jsonResponse([savedConfiguration()]);
        }
        if (input === "/api/v1/workspaces/company-1/folders") {
          return jsonResponse([
            { id: "folder-1", name: "규정", parent_id: null },
            { id: "folder-2", name: "상품", parent_id: null },
          ]);
        }
        if (input === "/api/v1/rag/search") {
          searchBody = JSON.parse(String(init?.body)) as Record<string, unknown>;
          return jsonResponse({
            status: "insufficient_evidence",
            answer: null,
            conflict_state: "none",
            conflicts: [],
            warnings: [],
            related_sources: [],
            configuration_version: {
              configuration_id: "configuration-1",
              version_id: "configuration-version-1",
              version: 3,
            },
            experimental: false,
          });
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("checkbox", { name: /전사 규정/ }));
    await user.click(await screen.findByRole("checkbox", { name: "전사 규정 / 규정" }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "저장된 RAG 구성" }),
      "configuration-1",
    );
    await user.type(screen.getByRole("searchbox", { name: "검색 질문" }), "환매 규정");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));

    expect(searchBody).toMatchObject({ folder_ids: ["folder-1"] });
  });

  it("keeps an immutable submitted context and ignores a cancelled late response", async () => {
    const firstSearch = deferred<Response>();
    const secondSearch = deferred<Response>();
    const searchSignals: AbortSignal[] = [];
    let searchCount = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
        const metadata = processingMetadataResponse(input);
        if (metadata) return Promise.resolve(metadata);
        if (input === "/api/v1/workspaces") {
          return Promise.resolve(
            jsonResponse([
              { id: "company-1", name: "전사 규정", kind: "company", expires_at: null },
              { id: "personal-1", name: "개인 리서치", kind: "personal", expires_at: null },
            ]),
          );
        }
        if (input === "/api/v1/rag/configurations") {
          return Promise.resolve(
            jsonResponse([
              savedConfiguration({ id: "configuration-a", name: "구성 A" }),
              savedConfiguration({
                id: "configuration-b",
                version_id: "selected-configuration-version-b",
                name: "구성 B",
                evaluation_state: "pending",
                experimental: true,
                is_default: false,
              }),
            ]),
          );
        }
        if (input === "/api/v1/workspaces/company-1/folders") {
          return Promise.resolve(
            jsonResponse([{ id: "folder-a", name: "전사 폴더", parent_id: null }]),
          );
        }
        if (input === "/api/v1/workspaces/personal-1/folders") {
          return Promise.resolve(
            jsonResponse([{ id: "folder-b", name: "개인 폴더", parent_id: null }]),
          );
        }
        if (input === "/api/v1/rag/search") {
          searchSignals.push(init?.signal as AbortSignal);
          searchCount += 1;
          return searchCount === 1 ? firstSearch.promise : secondSearch.promise;
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    );

    const company = await screen.findByRole("checkbox", { name: /전사 규정/ });
    await user.click(company);
    await user.click(await screen.findByRole("checkbox", { name: "전사 규정 / 전사 폴더" }));
    const configuration = screen.getByRole("combobox", { name: "저장된 RAG 구성" });
    const query = screen.getByRole("searchbox", { name: "검색 질문" });
    await user.selectOptions(configuration, "configuration-a");
    await user.type(query, "첫 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));

    expect(company).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: /개인 리서치/ })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "전사 규정 / 전사 폴더" })).toBeDisabled();
    expect(configuration).toBeDisabled();
    expect(query).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "검색 취소" }));
    expect(searchSignals[0].aborted).toBe(true);
    await user.click(company);
    await user.click(screen.getByRole("checkbox", { name: /개인 리서치/ }));
    await user.click(await screen.findByRole("checkbox", { name: "개인 리서치 / 개인 폴더" }));
    await user.selectOptions(configuration, "configuration-b");
    await user.click(screen.getByRole("checkbox", { name: "평가 전 구성을 실험 검색에 사용" }));
    await user.clear(query);
    await user.type(query, "두 번째 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));

    expect(screen.getByRole("checkbox", { name: "평가 전 구성을 실험 검색에 사용" })).toBeDisabled();
    secondSearch.resolve(
      jsonResponse({
        status: "supported",
        answer: evidenceAnswer({ workspace_id: "personal-1", folder_id: "folder-b" }),
        conflict_state: "none",
        conflicts: [],
        warnings: [],
        related_sources: [
          {
            document_id: "document-related-b",
            asset_version_id: "asset-version-related-b",
            asset_version_number: 3,
            workspace_id: "personal-1",
            folder_id: "folder-b",
            projection_id: "projection-related-b",
            chunk_id: "chunk-related-b",
            title: "두 번째 관련 문서.md",
            media_type: "text/markdown",
            section_path: [],
            fused_score: 0.4,
          },
        ],
        configuration_version: {
          configuration_id: "configuration-b",
          version_id: "configuration-version-b",
          version: 3,
        },
        experimental: true,
      }),
    );

    const results = await screen.findByTestId("submitted-search-result");
    expect(within(results).getByText("두 번째 질문")).toBeVisible();
    expect(within(results).getAllByText(/구성 B/).length).toBeGreaterThan(0);
    expect(within(results).queryByText(/configuration-b/)).not.toBeInTheDocument();
    expect(within(results).queryByText(/configuration-version-b/)).not.toBeInTheDocument();
    expect(within(results).queryByText(/selected-configuration-version-b/)).not.toBeInTheDocument();
    expect(within(results).queryByText(/personal-1/)).not.toBeInTheDocument();
    expect(within(results).queryByText(/folder-b/)).not.toBeInTheDocument();
    expect(within(results).getAllByText("개인").length).toBeGreaterThan(0);
    expect(within(results).getAllByText(/개인 리서치/).length).toBeGreaterThan(0);
    expect(within(results).getAllByText(/개인 폴더/).length).toBeGreaterThan(0);
    expect(within(results).getAllByText(/실험 실행/).length).toBeGreaterThan(0);
    const related = within(results).getByRole("region", { name: "관련 문서" });
    expect(within(related).getByLabelText("사용한 저장 RAG 구성")).toHaveTextContent("구성 B");

    firstSearch.resolve(
      jsonResponse({
        status: "supported",
        answer: evidenceAnswer(),
        conflict_state: "none",
        conflicts: [],
        warnings: [],
        related_sources: [],
        configuration_version: {
          configuration_id: "configuration-a",
          version_id: "configuration-version-1",
          version: 3,
        },
        experimental: false,
      }),
    );
    await waitFor(() => expect(within(results).queryByText("첫 질문")).not.toBeInTheDocument());
    expect(within(results).queryByText(/구성 A/)).not.toBeInTheDocument();
  });

  it.each([
    [401, "internal_source_detail", "로그인이 필요합니다."],
    [404, "internal_source_detail", "검색 범위 또는 구성을 찾을 수 없습니다."],
    [409, "internal_source_detail", "선택한 검색 구성을 지금 사용할 수 없습니다."],
    [503, "internal_source_detail", "검색 서비스가 일시적으로 준비되지 않았습니다. 잠시 후 다시 시도해 주세요."],
    [504, "provider_timeout", "생성 서비스 응답 시간이 초과되었습니다."],
  ])("renders a truthful %i search failure without exposing server detail", async (status, code, message) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const metadata = processingMetadataResponse(input);
        if (metadata) return metadata;
        if (input === "/api/v1/workspaces") {
          return jsonResponse([
            { id: "company-1", name: "전사 규정", kind: "company", expires_at: null },
          ]);
        }
        if (input === "/api/v1/rag/configurations") {
          return jsonResponse([savedConfiguration()]);
        }
        if (input === "/api/v1/workspaces/company-1/folders") return jsonResponse([]);
        if (input === "/api/v1/rag/search") {
          return jsonResponse(
            {
              error: {
                code,
                message: "비공개 문서 제목이 포함된 서버 상세",
                correlation_id: "correlation-1",
              },
            },
            status,
          );
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole("checkbox", { name: /전사 규정/ }));
    fireEvent.change(screen.getByRole("combobox", { name: "저장된 RAG 구성" }), {
      target: { value: "configuration-1" },
    });
    fireEvent.change(screen.getByRole("searchbox", { name: "검색 질문" }), {
      target: { value: "환매 규정" },
    });
    fireEvent.click(screen.getByRole("button", { name: "질문 보내기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByText(/비공개 문서 제목/)).not.toBeInTheDocument();
  });

  it("reports an initial 401 without claiming that authorized data is empty", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const metadata = processingMetadataResponse(input);
        if (metadata) return metadata;
        if (input === "/api/v1/workspaces" || input === "/api/v1/rag/configurations") {
          return jsonResponse({ error: { code: "unauthorized", message: "Unauthorized", correlation_id: "test" } }, 401);
        }
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("로그인이 필요합니다.");
    expect(screen.queryByText("검색할 수 있는 지식 공간이 없습니다.")).not.toBeInTheDocument();
    expect(screen.queryByText("사용할 수 있는 저장 구성이 없습니다.")).not.toBeInTheDocument();
  });

  it("explains an unready index before submit and keeps search disabled", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const metadata = processingMetadataResponse(input);
        if (metadata) return metadata;
        if (input === "/api/v1/workspaces") {
          return jsonResponse([
            { id: "company-1", name: "전사 규정", kind: "company", expires_at: null },
          ]);
        }
        if (input === "/api/v1/rag/configurations") {
          return jsonResponse([savedConfiguration({ search_ready: false })]);
        }
        if (input === "/api/v1/workspaces/company-1/folders") return jsonResponse([]);
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );
    const user = userEvent.setup();

    render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    );

    await user.click(await screen.findByRole("checkbox", { name: /전사 규정/ }));
    await user.selectOptions(
      screen.getByRole("combobox", { name: "저장된 RAG 구성" }),
      "configuration-1",
    );
    await user.type(screen.getByRole("searchbox", { name: "검색 질문" }), "환매 규정");

    expect(screen.getByRole("status", { name: "RAG 서비스 준비 상태" })).toHaveTextContent(
      "선택한 구성의 검색 색인이 아직 준비되지 않았습니다",
    );
    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
  });

  it("announces empty authorized scopes and saved configurations", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const metadata = processingMetadataResponse(input);
        if (metadata) return metadata;
        if (input === "/api/v1/workspaces") return jsonResponse([]);
        if (input === "/api/v1/rag/configurations") return jsonResponse([]);
        throw new Error(`Unexpected request: ${String(input)}`);
      }),
    );

    render(
      <MemoryRouter>
        <SearchPage />
      </MemoryRouter>,
    );

    expect(await screen.findByText("검색할 수 있는 지식 공간이 없습니다.")).toHaveAttribute(
      "role",
      "status",
    );
    expect(screen.getByText("사용할 수 있는 저장 구성이 없습니다.")).toHaveAttribute(
      "role",
      "status",
    );
  });
});

function processingMetadataResponse(input: RequestInfo | URL): Response | null {
  if (input === "/api/v1/rag/profiles/generation") {
    return jsonResponse([generationProfile("generation-1", "deployment-external")]);
  }
  if (input === "/api/v1/rag/deployments/options") {
    return jsonResponse([deploymentOption()]);
  }
  return null;
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function evidenceAnswer(sourceOverrides: Record<string, unknown> = {}) {
  return {
    excerpt: "환매 요청은 영업일 기준 3일 전에 접수해야 합니다.",
    source: {
      document_id: "document-1",
      asset_version_id: "asset-version-1",
      asset_version_number: 4,
      workspace_id: "company-1",
      folder_id: null,
      projection_id: "projection-1",
      chunk_id: "chunk-1",
      evidence_unit_id: "evidence-1",
      element_id: "element-1",
      title: "환매 규정.txt",
      media_type: "text/plain",
      section_path: ["제3조", "환매"],
      location: {
        element_id: "element-1",
        page: null,
        char_start: 0,
        char_end: 29,
        bbox: null,
      },
      ...sourceOverrides,
    },
    highlights: [
      {
        kind: "keyword",
        evidence_unit_id: "evidence-1",
        text: "영업일 기준 3일",
        char_start: 6,
        char_end: 15,
        page: null,
        bbox: null,
        score: null,
        warnings: [],
      },
    ],
    keyword_coverage: 0.8,
    semantic_score: 0.91,
    warnings: [],
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

function savedConfiguration(
  overrides: Partial<SavedConfiguration> = {},
): SavedConfiguration {
  return {
    id: "configuration-1",
    version_id: "configuration-version-1",
    name: "승인된 하이브리드",
    version: 3,
    owner_id: "owner-1",
    workspace_ids: ["company-1", "personal-1"],
    indexing_profile_id: "indexing-1",
    retrieval_profile_id: "retrieval-1",
    generation_profile_id: "generation-1",
    answer_policy: {
      id: "policy-1",
      version: 1,
      mode: "generative",
      min_keyword_coverage: 0.5,
      min_semantic_score: 0.7,
      require_complete_provenance: true,
      conflict_mode: "separate_sources",
    },
    evaluation_state: "passed",
    is_default: true,
    is_system: false,
    experimental: false,
    search_ready: true,
    answer_ready: true,
    service_ready: true,
    search_reasons: [],
    answer_reasons: [],
    ...overrides,
  };
}

function generationProfile(id: string, deploymentVersionId: string): GenerationProfile {
  return {
    id,
    kind: "generation" as const,
    name: `${id} profile`,
    version: 1,
    config: {},
    bindings: [],
    deployment_version_id: deploymentVersionId,
    legacy: false,
    readiness: { ready: true, reason_codes: [] },
    evaluation_state: "passed" as const,
    is_default: false,
  };
}

function deploymentOption(overrides: Partial<DeploymentOption> = {}): DeploymentOption {
  return {
    deployment_version_id: "deployment-external",
    display_name: "OpenAI 금융 답변",
    model_name: "OpenAI GPT-5 mini",
    model_version: 2,
    provider: "openai_responses" as const,
    provider_model_id: "gpt-5-mini-2025-08-07",
    location: "external" as const,
    external_transfer: true,
    allowed_environments: ["production" as const],
    capabilities: ["structured_output" as const, "contextualization" as const],
    readiness: { ready: true, reason_codes: [] },
    approval: {
      required: true as const,
      disclosure_version: "external-generation-v1" as const,
      disclosure: "현재 질문, 제한된 이전 대화와 선별된 문서 근거가 OpenAI 외부 API로 전송됩니다.",
      transmitted_data_categories: ["question", "bounded_history", "evidence"],
    },
    ...overrides,
  };
}
