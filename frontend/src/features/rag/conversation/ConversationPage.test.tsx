import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, vi } from "vitest";

import type { Domain } from "../domains/api";
import type { DomainSearchResult, Evidence } from "./api";
import { ConversationPage as ConversationPageImpl } from "./ConversationPage";
import { buildScopeSnapshot } from "./ScopeSelector";
import { selectionFromDocuments } from "./types";

function ConversationPage(props: React.ComponentProps<typeof ConversationPageImpl>) {
  return <ConversationPageImpl {...props} initialWorkspaceIds={props.initialWorkspaceIds ?? props.domain.workspace_options.map(({ id }) => id)} />;
}

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));


// Scope, consent and source-viewer tests use a session-service seam. The separate
// ConversationSessions suite exercises the real session transport and persistence UI.
vi.mock("./sessions-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./sessions-api")>();
  const { searchDomain } = await import("./api");
  const sessions = new Map<string, import("./sessions-api").ConversationDetail>();
  return {...actual,
    listConversations: async () => [],
    createConversation: async () => {
      const detail = {id: crypto.randomUUID(), title: "새 대화 2026-09-21", revision: 1, created_at: "2026-09-21", updated_at: "2026-09-21", turns: []};
      sessions.set(detail.id, detail); return detail;
    },
    sendConversationTurn: async (slug: string, id: string, request: import("./sessions-api").TurnRequest, signal?: AbortSignal) => {
      const response = await searchDomain(slug, request, signal);
      const previous = sessions.get(id)!;
      const detail = {...previous, revision: previous.revision + 1, turns: [...previous.turns, {
        id: request.request_id, request_id: request.request_id, sequence: previous.turns.length + 1, status: "completed" as const,
        query: request.query, response, request_scope: {connection_version_id: request.connection_version_id, workspace_ids: request.workspace_ids, folder_ids: request.folder_ids ?? [], document_ids: request.document_ids ?? null},
        segment: 1, error_code: null, redacted: false, execution_terminated: true, created_at: "2026-09-21", updated_at: "2026-09-21",
      }]};
      sessions.set(id, detail); return detail;
    },
    getConversation: async (_slug: string, id: string) => sessions.get(id)!,
    cancelConversationTurn: async (_slug: string, id: string) => sessions.get(id)!,
  };
});
beforeEach(() => window.history.replaceState(null, "", "/"));

afterEach(() => vi.unstubAllGlobals());

describe("ConversationPage", () => {
  it("uses the composer plus as the only document selection entry", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json([])));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);
    expect(screen.queryByRole("button", { name: "파일 선택" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "문서 추가" }));
    expect(screen.getByRole("button", { name: "기존 문서 선택" })).toBeVisible();
  });
  it("preserves the applied bounded selection when a read-only draft closes without Apply", async () => {
    const folder = { id: "folder-1", workspace_id: "workspace-1", metadata_revision: 1, name: "리스크", parent_id: null, has_children: false };
    const scoped = { ...selectedDocument(), folder_id: folder.id };
    const posts: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/capabilities")) return jsonResponse({ read: true, write: true, delete: false, manage_members: false });
      if (path.endsWith("/folders")) return jsonResponse(path.includes("workspace-1") ? [folder] : []);
      if (path.endsWith("/library")) return jsonResponse({ domain_id: "domain-1", display_name: "자산운용", connection_version_id: "connection-1", selection_limit: 3, workspace_options: domain().workspace_options });
      if (init?.method === "POST") { posts.push(init); throw new Error("Unexpected mutation"); }
      if (path.endsWith(`/documents/${scoped.id}`)) return jsonResponse(scoped);
      if (path.includes("/library/workspaces/workspace-1")) return jsonResponse({ ...libraryPage(), folder: path.includes("folder_id=folder-1") ? folder : null, folders: path.includes("folder_id=folder-1") ? [] : [folder], documents: [scoped] });
      throw new Error(`Unexpected path: ${path}`);
    }));
    const user = userEvent.setup(); render(<ConversationPage domain={domain()} />);
    await user.click(screen.getByRole("button", { name: "검색 범위 열기" }));
    await user.click(screen.getByRole("radio", { name: "폴더" }));
    await user.click(await screen.findByRole("checkbox", { name: /회사 규정 \/ 리스크/ }));
    await user.click(screen.getByRole("button", { name: "범위 적용" }));
    await user.click(screen.getByRole("button", { name: "문서 추가" }));
    await user.click(screen.getByRole("button", { name: "기존 문서 선택" }));
    await user.click(await screen.findByRole("checkbox", { name: "운용 규정.md 선택" }));
    await user.click(screen.getByRole("button", { name: "선택 적용" }));
    expect(screen.getByRole("button", { name: "문서 추가" })).toHaveFocus();
    await user.type(screen.getByRole("textbox", { name: "질문" }), "합성 질문");
    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "문서 추가" }));
    await user.click(screen.getByRole("button", { name: "기존 문서 선택" }));
    const panel = await screen.findByRole("dialog", { name: "파일 선택" });
    const selected = await within(panel).findByRole("checkbox", { name: "운용 규정.md 선택" });
    expect(selected).toBeChecked();
    expect(within(panel).queryByRole("button", { name: /이동$|문서 올리기|새 폴더|새 버전 올리기/ })).not.toBeInTheDocument();
    await user.click(selected);
    expect(selected).not.toBeChecked();
    await user.click(within(panel).getByRole("button", { name: "닫기" }));
    expect(screen.queryByRole("dialog", { name: "파일 선택" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "문서 추가" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "문서 추가" }));
    await user.click(screen.getByRole("button", { name: "기존 문서 선택" }));
    expect(await screen.findByRole("checkbox", { name: "운용 규정.md 선택" })).toBeChecked();
    expect(posts).toHaveLength(0);
  }, 20_000);
  it("preserves an applied folder id when the refreshed folder listing no longer contains it", () => {
    expect(buildScopeSnapshot(domain(), ["workspace-1"], ["folder-withdrawn"], {}, null)).toMatchObject({
      workspaceIds: ["workspace-1"],
      folderIds: ["folder-withdrawn"],
      documentIds: null,
    });
  });
  it("starts with no implicit workspace scope and applies workspace drafts explicitly", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      throw new Error(`Unexpected request: ${String(input)}`);
    }));
    const user = userEvent.setup();
    render(<ConversationPageImpl domain={domain()} />);

    await user.type(screen.getByRole("textbox", { name: "질문" }), "명시 범위 질문");
    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
    expect(screen.getByText("검색 범위를 선택해 적용하세요.")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "검색 범위 열기" }));
    await user.click(screen.getByRole("checkbox", { name: "회사 공간 · 회사 규정" }));
    await user.click(screen.getByRole("button", { name: "취소" }));
    expect(screen.getByText("검색 범위를 선택해 적용하세요.")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "검색 범위 열기" }));
    expect(screen.getByRole("checkbox", { name: "회사 공간 · 회사 규정" })).not.toBeChecked();
    await user.click(screen.getByRole("checkbox", { name: "회사 공간 · 회사 규정" }));
    await user.click(screen.getByRole("button", { name: "범위 적용" }));
    expect(screen.getByText("회사 규정 · 선택 공간 전체")).toBeVisible();
  }, 15_000);

  it("keeps an empty folder mode after the last folder is removed", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/workspaces/workspace-1/folders") return jsonResponse([{ id: "folder-1", workspace_id: "workspace-1", name: "리스크", parent_id: null }]);
      if (String(input).includes("/folders")) return jsonResponse([]);
      throw new Error(`Unexpected request: ${String(input)}`);
    }));
    const user = userEvent.setup();
    render(<ConversationPageImpl domain={domain()} />);
    await user.click(await screen.findByRole("button", { name: "검색 범위 열기" }));
    await user.click(screen.getByRole("radio", { name: "폴더" }));
    await user.click(screen.getByRole("checkbox", { name: "회사 공간 · 회사 규정" }));
    await user.click(await screen.findByRole("checkbox", { name: /회사 규정 \/ 리스크/ }));
    await user.click(screen.getByRole("button", { name: "범위 적용" }));
    await user.click(screen.getByRole("button", { name: "검색 범위 열기" }));
    await user.click(screen.getByRole("checkbox", { name: "회사 공간 · 회사 규정" }));
    expect(screen.queryByRole("checkbox", { name: /회사 규정 \/ 리스크/ })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "범위 적용" }));
    expect(screen.getByText("하나 이상의 폴더를 선택하세요.")).toBeVisible();
    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
  });
  it("sends an initial server-resolved document selection without widening workspace or folder scope", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return jsonResponse({ ...searchResult(1), selected_scope: selectedScope() });
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} initialSelection={selectionFromDocuments([selectedDocument()])} />);

    expect(screen.getByText("선택 문서 운용 규정.md")).toBeVisible();
    await user.type(screen.getByRole("textbox", { name: "질문" }), "선택 문서 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    await screen.findByText("답변 1");

    expect(bodies[0]).toMatchObject({
      workspace_ids: ["workspace-1"],
      folder_ids: [],
      document_ids: ["document-1"],
    });
  });

  it("collects diagnostics by default without widening the selected document scope", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return jsonResponse({ ...searchResult(1), selected_scope: selectedScope() });
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} initialSelection={selectionFromDocuments([selectedDocument()])} />);

    await user.type(screen.getByRole("textbox", { name: "질문" }), "선택 문서 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    await screen.findByText("답변 1");

    expect(bodies[0]).toMatchObject({
      workspace_ids: ["workspace-1"],
      folder_ids: [],
      document_ids: ["document-1"],
      include_diagnostics: true,
    });
  });

  it("keeps an explicit empty selection after the last document is removed and blocks sending", async () => {
    const fetcher = vi.fn(async (...args: Parameters<typeof fetch>) => {
      const [input] = args;
      const path = String(input);
      if (path.includes("/folders")) return jsonResponse([]);
      if (path.endsWith("/library")) return jsonResponse({ domain_id: "domain-1", display_name: "자산운용", connection_version_id: "connection-1", selection_limit: 2, workspace_options: domain().workspace_options });
      if (path.endsWith("/library/workspaces/workspace-1")) return jsonResponse(libraryPage());
      throw new Error(`Unexpected request: ${path}`);
    });
    vi.stubGlobal("fetch", fetcher);
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} initialSelection={selectionFromDocuments([selectedDocument()])} />);

    await user.click(screen.getByRole("button", { name: "문서 추가" }));
    await user.click(screen.getByRole("button", { name: "기존 문서 선택" }));
    await user.click(await screen.findByRole("checkbox", { name: "운용 규정.md 선택" }));
    await user.click(screen.getByRole("button", { name: "선택 적용" }));
    expect(screen.getByText("선택 문서 없음")).toBeVisible();
    await user.type(screen.getByRole("textbox", { name: "질문" }), "전체 검색 금지");
    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
    expect(fetcher.mock.calls.some(([, init]) => init?.method === "POST")).toBe(false);
  });
  it("selects a file directly from the initial empty scope without requiring preview", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/folders")) return jsonResponse([]);
      if (path.endsWith("/library")) return jsonResponse({ domain_id: "domain-1", display_name: "자산운용", connection_version_id: "connection-1", selection_limit: 2, workspace_options: domain().workspace_options });
      if (path.endsWith("/library/workspaces/workspace-1")) return jsonResponse(libraryPage());
      if (path.endsWith("/search")) { bodies.push(JSON.parse(String(init?.body))); return jsonResponse({ ...searchResult(1), selected_scope: selectedScope() }); }
      throw new Error(`Unexpected request: ${path}`);
    }));
    const user = userEvent.setup();
    render(<ConversationPageImpl domain={domain()} />);
    await user.click(screen.getByRole("button", { name: "문서 추가" }));
    await user.click(screen.getByRole("button", { name: "기존 문서 선택" }));
    await user.click(await screen.findByRole("checkbox", { name: "운용 규정.md 선택" }));
    await user.click(screen.getByRole("button", { name: "선택 적용" }));
    await user.type(screen.getByRole("textbox", { name: "질문" }), "바로 파일 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    await screen.findByText("답변 1");
    expect(bodies[0]).toMatchObject({ workspace_ids: ["workspace-1"], folder_ids: [], document_ids: ["document-1"] });
  });
  it("requires Codex classification and fresh consent for each question and scope", async () => {
    const calls: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      calls.push(init!); return jsonResponse(searchResult(calls.length));
    }));
    const current = externalDomain();
    current.generation_execution_preview = { ...current.generation_execution_preview!, provider: "development_codex_exec", disclosure_version: "codex-external-generation-v1", requested_provider_model_id: "selected-model", observed_provider_model_id: null, model_identity_status: "unknown" };
    const user = userEvent.setup();
    const { rerender } = render(<ConversationPage domain={current} />);
    await user.type(screen.getByRole("textbox", { name: "질문" }), "합성 질문");
    await user.click(screen.getByRole("checkbox", { name: "이번 질문의 외부 처리를 확인했습니다" }));
    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
    await user.selectOptions(screen.getByLabelText("이번 질문과 전송 이력의 분류"), "synthetic");
    await user.click(screen.getByRole("checkbox", { name: "이번 질문의 외부 처리를 확인했습니다" }));
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    await screen.findByText("답변 1");
    expect(calls[0].headers).toMatchObject({ "x-codex-request": "1", "content-type": "application/json" });
    expect(JSON.parse(String(calls[0].body)).codex_input_approval).toEqual({ classification: "synthetic", consented: true, disclosure_version: "codex-external-generation-v1" });
    expect(screen.getByLabelText("이번 질문과 전송 이력의 분류")).toHaveValue("");
    expect(screen.getByRole("checkbox", { name: "이번 질문의 외부 처리를 확인했습니다" })).not.toBeChecked();
    await user.selectOptions(screen.getByLabelText("이번 질문과 전송 이력의 분류"), "public");
    await user.click(screen.getByRole("checkbox", { name: "이번 질문의 외부 처리를 확인했습니다" }));
    await user.click(screen.getByRole("button", { name: "검색 범위 열기" }));
    await user.click(screen.getByRole("checkbox", { name: /회사 규정/ }));
    expect(screen.getByRole("checkbox", { name: "이번 질문의 외부 처리를 확인했습니다" })).toBeChecked();
    await user.click(screen.getByRole("button", { name: "범위 적용" }));
    expect(screen.getByRole("checkbox", { name: "이번 질문의 외부 처리를 확인했습니다" })).not.toBeChecked();
    await act(async () => { rerender(<ConversationPage domain={{ ...current, connection_version: { id: "new-connection", version: 3 } }} />); });
    expect(screen.getByLabelText("이번 질문과 전송 이력의 분류")).toHaveValue("");
    expect(calls).toHaveLength(1);
  });
  it("sends no client-owned history across questions", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      if (String(input).endsWith("/search")) {
        bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return jsonResponse(searchResult(bodies.length));
      }
      throw new Error(`Unexpected request: ${String(input)}`);
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);

    const textbox = screen.getByRole("textbox", { name: "질문" });
    expect(textbox).toBeVisible();
    expect(screen.queryByLabelText("RAG 구성")).not.toBeInTheDocument();
    await user.type(textbox, "위험 한도는 얼마야?");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    expect(await screen.findByText("답변 1")).toBeVisible();
    await user.type(textbox, "언제부터 적용돼?");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    expect(await screen.findByText("답변 2")).toBeVisible();

    expect(bodies[0]).toMatchObject({
      connection_version_id: "connection-1",
      query: "위험 한도는 얼마야?",
      workspace_ids: ["workspace-1", "workspace-2"],
      folder_ids: [],
      top_k: 10,
    });
    expect(bodies[0]).not.toHaveProperty("history");
    expect(bodies[1]).not.toHaveProperty("history");
    expect(bodies[1]).toMatchObject({include_diagnostics: true});
  });

  it("preserves the transcript and answer scopes while a folder change clears next-request history", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input) === "/api/v1/workspaces/workspace-1/folders") {
        return jsonResponse([{ id: "folder-1", workspace_id: "workspace-1", name: "리스크", parent_id: null }]);
      }
      if (String(input).includes("/folders")) return jsonResponse([]);
      bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return jsonResponse(searchResult(bodies.length));
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);
    const textbox = screen.getByRole("textbox", { name: "질문" });

    await user.type(textbox, "첫 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    expect(await screen.findByText("답변 1")).toBeVisible();
    const firstMessage = screen.getByRole("article", { name: "첫 질문에 대한 답변" });
    expect(firstMessage).toHaveTextContent("응답 범위: 회사 규정, 개인 연구 · 선택 공간 전체");

    await user.click(screen.getByRole("button", { name: "검색 범위 열기" }));
    await user.click(screen.getByRole("radio", { name: "폴더" }));
    await user.click(await screen.findByRole("checkbox", { name: /회사 규정 \/ 리스크/ }));
    await user.click(screen.getByRole("button", { name: "범위 적용" }));
    expect(screen.getByText("검색 범위 변경")).toBeVisible();
    expect(screen.getByText("답변 1")).toBeVisible();

    await user.type(textbox, "새 범위 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    expect(await screen.findByText("답변 2")).toBeVisible();
    expect(bodies[1]).toMatchObject({ folder_ids: ["folder-1"] });
    expect(screen.getByRole("article", { name: "새 범위 질문에 대한 답변" })).toHaveTextContent(
      "응답 범위: 회사 규정 · 폴더 리스크",
    );
  });

  it("blocks sending when all workspaces are deselected and locks scope while a request is pending", async () => {
    let resolveSearch!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      return new Promise<Response>((resolve) => { resolveSearch = resolve; });
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);
    await user.click(screen.getByRole("button", { name: "검색 범위 열기" }));
    await user.click(screen.getByRole("checkbox", { name: /회사 규정/ }));
    await user.click(screen.getByRole("checkbox", { name: /개인 연구/ }));
    await user.click(screen.getByRole("button", { name: "범위 적용" }));
    await user.type(screen.getByRole("textbox", { name: "질문" }), "보낼 수 없는 질문");
    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
    expect(screen.getByText("하나 이상의 지식 공간을 선택하세요.")).toBeVisible();

    await user.click(screen.getByRole("button", { name: "검색 범위 열기" }));
    await user.click(screen.getByRole("checkbox", { name: /회사 규정/ }));
    await user.click(screen.getByRole("button", { name: "범위 적용" }));
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    expect(screen.getByRole("button", { name: "검색 범위 열기" })).toBeDisabled();
    resolveSearch(jsonResponse(searchResult(1)));
    await screen.findByText("답변 1");
  });

  it("ignores a late response after starting a new conversation", async () => {
    let resolveSearch!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      return new Promise<Response>((resolve) => { resolveSearch = resolve; });
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);
    await user.type(screen.getByRole("textbox", { name: "질문" }), "늦은 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    await user.click(screen.getByRole("button", { name: "새 대화" }));
    resolveSearch(jsonResponse(searchResult(1)));

    await waitFor(() => expect(screen.queryByText("답변 1")).not.toBeInTheDocument());
    expect(screen.getByRole("textbox", { name: "질문" })).toHaveValue("");
  });

  it("requires an explicit context reset after a selected-scope 409 and never retries automatically", async () => {
    let searchCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      searchCalls += 1;
      return searchCalls === 1 ? jsonResponse({ ...searchResult(1), selected_scope: selectedScope() }) : errorResponse(409, "conversation_scope_changed", "private scope detail");
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} initialSelection={selectionFromDocuments([selectedDocument()])} />);
    const textbox = screen.getByRole("textbox", { name: "질문" });

    await user.type(textbox, "첫 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    await screen.findByText("답변 1");
    await user.type(textbox, "버전 변경 후 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("문서 버전 또는 선택 범위가 변경되었습니다");
    expect(searchCalls).toBe(2);
    expect(screen.queryByRole("button", { name: "같은 질문 다시 시도" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "변경된 범위로 새 문맥 시작" }));
    expect(searchCalls).toBe(2);
    expect(screen.getByText("검색 범위 변경")).toBeVisible();
  });

  it("opens the exact server-used version from a completed selected response and restores focus", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/folders")) return jsonResponse([]);
      if (path.endsWith("/search")) return jsonResponse({ ...searchResult(1), selected_scope: selectedScope() });
      if (path.endsWith("/library/documents/document-1/versions")) return jsonResponse({ items: [{ id: "asset-version-used", number: 2, media_type: "text/markdown", size: 12, status: "ready" }], next_cursor: null });
      if (path.endsWith("/versions/asset-version-used/preview")) return jsonResponse({ asset_version_id: "asset-version-used", document_id: "document-1", kind: "text", name: "운용 규정 v2.md", page_count: null, size: 12, text: "응답에 사용된 정확한 원문", version: 2 });
      throw new Error(`Unexpected request: ${path}`);
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} initialSelection={selectionFromDocuments([selectedDocument()])} />);
    await user.type(screen.getByRole("textbox", { name: "질문" }), "정확한 버전 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    const opener = await screen.findByRole("button", { name: "운용 규정.md 사용 버전 원문 열기" });
    await user.click(opener);

    expect(await screen.findByText("응답에 사용된 정확한 원문")).toBeVisible();
    expect(screen.queryByRole("button", { name: "이 버전에 대한 Codex 승인 요청" })).not.toBeInTheDocument();
    expect(vi.mocked(fetch).mock.calls.every(([input]) => !String(input).includes("evidence-approval"))).toBe(true);
    await user.keyboard("{Escape}");
    expect(screen.queryByText("응답에 사용된 정확한 원문")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("remounts the original viewer when another answer selects a different version", async () => {
    let searches = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.includes("/folders")) return jsonResponse([]);
      if (path.endsWith("/search")) {
        searches += 1;
        return jsonResponse({ ...searchResult(searches), selected_scope: { identities: [{ ...selectedScope().identities[0], asset_version_id: `asset-version-${searches}` }], fingerprint: `scope-${searches}` } });
      }
      if (path.endsWith("/library/documents/document-1/versions")) return jsonResponse({ items: [1, 2].map((number) => ({ id: `asset-version-${number}`, number, media_type: "text/markdown", size: 12, status: "ready" })), next_cursor: null });
      const match = path.match(/versions\/(asset-version-[12])\/preview$/);
      if (match) return jsonResponse({ asset_version_id: match[1], document_id: "document-1", kind: "text", name: "운용 규정.md", page_count: null, size: 12, text: `${match[1]} 원문`, version: Number(match[1].at(-1)) });
      throw new Error(`Unexpected request: ${path}`);
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} initialSelection={selectionFromDocuments([selectedDocument()])} />);
    const textbox = screen.getByRole("textbox", { name: "질문" });
    await user.type(textbox, "첫 버전 질문"); await user.click(screen.getByRole("button", { name: "질문 보내기" })); await screen.findByText("답변 1");
    await user.type(textbox, "둘째 버전 질문"); await user.click(screen.getByRole("button", { name: "질문 보내기" })); await screen.findByText("답변 2");
    const openers = screen.getAllByRole("button", { name: "운용 규정.md 사용 버전 원문 열기" });
    await user.click(openers[0]); expect(await screen.findByText("asset-version-1 원문")).toBeVisible();
    await user.click(openers[1]); expect(await screen.findByText("asset-version-2 원문")).toBeVisible();
    expect(screen.queryByText("asset-version-1 원문")).not.toBeInTheDocument();
  });

  it("supports Enter send, Shift+Enter newline and blocks IME composition send", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      return jsonResponse(searchResult(bodies.length));
    }));
    render(<ConversationPage domain={domain()} />);
    const textbox = screen.getByRole("textbox", { name: "질문" });

    fireEvent.change(textbox, { target: { value: "한글 조합" } });
    fireEvent.compositionStart(textbox);
    fireEvent.keyDown(textbox, { key: "Enter", code: "Enter", isComposing: true });
    expect(bodies).toHaveLength(0);
    fireEvent.compositionEnd(textbox);
    fireEvent.keyDown(textbox, { key: "Enter", code: "Enter", shiftKey: true });
    expect(bodies).toHaveLength(0);
    fireEvent.keyDown(textbox, { key: "Enter", code: "Enter" });
    expect(await screen.findByText("답변 1")).toBeVisible();
    expect(bodies).toHaveLength(1);
  });

  it("opens a matching citation in the reusable source panel and restores focus on Escape", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      if (String(input).includes("normalized-text")) return jsonResponse(normalizedText());
      return jsonResponse(searchResult(1));
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);
    await user.type(screen.getByRole("textbox", { name: "질문" }), "근거 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    const citation = await screen.findByRole("button", { name: "인용 1: 환매 규정" });
    await user.click(citation);

    const panel = await screen.findByRole("dialog", { name: "원문 근거" });
    expect(within(panel).getByRole("heading", { name: "환매 규정" })).toBeVisible();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "원문 근거" })).not.toBeInTheDocument();
    expect(citation).toHaveFocus();
  });

  it("requires a per-send acknowledgement for external processing without claiming server approval", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      return jsonResponse(searchResult(1));
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain({ generation_execution_preview: {
      deployment_name: "외부 답변",
      model_name: "외부 모델",
      model_version: 2,
      provider: "openai_responses",
      disclosure_version: "external-generation-v1",
      location: "external",
      external_transfer: true,
      disclosure: "현재 질문과 제한된 이전 대화, 선별 근거가 외부 API로 전송됩니다.",
    } })} />);
    await user.type(screen.getByRole("textbox", { name: "질문" }), "외부 처리 질문");

    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
    const consent = screen.getByRole("checkbox", { name: "이번 질문의 외부 처리를 확인했습니다" });
    expect(screen.getByText(/관리자가 저장한 전송 승인과 별개/)).toBeVisible();
    await user.click(consent);
    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeEnabled();
  });

  it("preserves the current workspace and folder intersection when selecting documents", async () => {
    const scopedDocument = { ...selectedDocument(), folder_id: "folder-1" };
    const bodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/workspaces/workspace-1/folders") return jsonResponse([{ id: "folder-1", workspace_id: "workspace-1", name: "리스크", parent_id: null }]);
      if (path === "/api/v1/workspaces/workspace-2/folders") return jsonResponse([{ id: "folder-2", workspace_id: "workspace-2", name: "개인", parent_id: null }]);
      if (path.endsWith("/folders")) return jsonResponse([]);
      if (path.endsWith("/library")) return jsonResponse({ domain_id: "domain-1", display_name: "자산운용", connection_version_id: "connection-1", selection_limit: 3, workspace_options: domain().workspace_options });
      if (path.includes("/library/workspaces/workspace-1")) return jsonResponse({ ...libraryPage(), folder: path.includes("folder_id=folder-1") ? { id: "folder-1", name: "리스크", parent_id: null } : null, documents: [scopedDocument] });
      if (path.endsWith("/search")) { bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>); return jsonResponse({ ...searchResult(1), selected_scope: selectedScope() }); }
      throw new Error(`Unexpected request: ${path}`);
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);

    await user.click(screen.getByRole("button", { name: "검색 범위 열기" }));
    await user.click(screen.getByRole("radio", { name: "폴더" }));
    await user.click(await screen.findByRole("checkbox", { name: /리스크/ }));
    await user.click(screen.getByRole("checkbox", { name: /개인 연구 \/ 개인/ }));
    await user.click(screen.getByRole("button", { name: "범위 적용" }));
    await user.click(screen.getByRole("button", { name: "문서 추가" }));
    await user.click(screen.getByRole("button", { name: "기존 문서 선택" }));
    await screen.findByRole("dialog", { name: "파일 선택" });
    expect(screen.getByRole("button", { name: "개인 연구" })).toBeVisible();
    await user.click(await screen.findByRole("checkbox", { name: `${scopedDocument.name} 선택` }));
    await user.click(screen.getByRole("button", { name: "선택 적용" }));
    await user.type(screen.getByRole("textbox", { name: "질문" }), "현재 범위 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    await screen.findByText("답변 1");

    expect(bodies[0]).toMatchObject({ workspace_ids: ["workspace-1"], folder_ids: ["folder-1"], document_ids: ["document-1"] });
  });

  it("clears ordinary external consent after document additions and removals", async () => {
    const second = { ...selectedDocument(), id: "document-2", name: "추가 문서.md" };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/folders")) return jsonResponse([]);
      if (path.endsWith("/library")) return jsonResponse({ domain_id: "domain-1", display_name: "자산운용", connection_version_id: "connection-1", selection_limit: 3, workspace_options: [domain().workspace_options[0]] });
      if (path.includes("/library/workspaces/workspace-1")) return jsonResponse({ ...libraryPage(), documents: [selectedDocument(), second] });
      throw new Error(`Unexpected request: ${path}`);
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={externalDomain()} initialSelection={selectionFromDocuments([selectedDocument()])} />);
    const consent = screen.getByRole("checkbox", { name: "이번 질문의 외부 처리를 확인했습니다" });

    await user.click(consent);
    await user.click(screen.getByRole("button", { name: "문서 추가" }));
    await user.click(screen.getByRole("button", { name: "기존 문서 선택" }));
    await user.click(await screen.findByRole("checkbox", { name: "추가 문서.md 선택" }));
    await user.click(screen.getByRole("button", { name: "선택 적용" }));
    expect(consent).not.toBeChecked();

    await user.click(consent);
    await user.click(screen.getByRole("button", { name: "문서 추가" }));
    await user.click(screen.getByRole("button", { name: "기존 문서 선택" }));
    await user.click(await screen.findByRole("checkbox", { name: "운용 규정.md 선택" }));
    await user.click(screen.getByRole("button", { name: "선택 적용" }));
    expect(consent).not.toBeChecked();
  });

  it("clears ordinary external consent on an explicit scope-context reset", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).endsWith("/folders")) return jsonResponse([]);
      return errorResponse(409, "conversation_scope_changed", "private scope detail");
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={externalDomain()} />);
    const consent = screen.getByRole("checkbox", { name: "이번 질문의 외부 처리를 확인했습니다" });
    await user.type(screen.getByRole("textbox", { name: "질문" }), "범위 변경 질문");
    await user.click(consent);
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    await screen.findByRole("button", { name: "변경된 범위로 새 문맥 시작" });
    await user.click(consent);
    await user.click(screen.getByRole("button", { name: "변경된 범위로 새 문맥 시작" }));

    expect(consent).not.toBeChecked();
  });

  it("consumes external processing acknowledgement when a failed request starts", async () => {
    let searchAttempts = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      searchAttempts += 1;
      throw new Error("network unavailable");
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={externalDomain()} />);
    await user.type(screen.getByRole("textbox", { name: "질문" }), "실패할 외부 질문");
    const consent = screen.getByRole("checkbox", { name: "이번 질문의 외부 처리를 확인했습니다" });
    await user.click(consent);
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("답변을 만들지 못했습니다.");
    expect(consent).not.toBeChecked();
    expect(screen.getByRole("button", { name: "같은 질문 다시 시도" })).toBeDisabled();
    expect(searchAttempts).toBe(1);
    await user.click(consent);
    expect(screen.getByRole("button", { name: "같은 질문 다시 시도" })).toBeEnabled();
  });

  it("requires fresh external processing acknowledgement after cancellation", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      return new Promise<Response>(() => undefined);
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={externalDomain()} />);
    await user.type(screen.getByRole("textbox", { name: "질문" }), "취소할 외부 질문");
    const consent = screen.getByRole("checkbox", { name: "이번 질문의 외부 처리를 확인했습니다" });
    await user.click(consent);
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    await user.click(screen.getByRole("button", { name: "답변 취소" }));

    expect(screen.getByRole("textbox", { name: "질문" })).toHaveValue("취소할 외부 질문");
    expect(consent).not.toBeChecked();
    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
    await user.click(consent);
    expect(screen.getByRole("button", { name: "질문 보내기" })).toBeEnabled();
  });

  it("handles the real citation validation error envelope without exposing its private message", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      return errorResponse(502, "citation_validation_failed", "private draft and validator detail");
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);
    await user.type(screen.getByRole("textbox", { name: "질문" }), "인용 검증 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("생성 답변의 근거 인용을 검증하지 못했습니다.");
    expect(alert).not.toHaveTextContent("private draft and validator detail");
    expect(within(alert).getByRole("button", { name: "같은 질문 다시 시도" })).toBeVisible();
  });

  it("requires fresh domain entry after a configuration workspace-policy denial", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      return errorResponse(403, "workspace_external_transfer_denied", "private policy detail");
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);
    const textbox = screen.getByRole("textbox", { name: "질문" });
    await user.type(textbox, "정책 확인 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("연결된 RAG 구성의 지식 공간 전송 정책이 외부 생성을 허용하지 않습니다.");
    expect(alert).not.toHaveTextContent("private policy detail");
    expect(within(alert).getByRole("link", { name: "도메인 선택으로 돌아가기" })).toHaveAttribute(
      "href",
      "/workshop/rag/search",
    );
    expect(within(alert).queryByRole("button", { name: "같은 질문 다시 시도" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "새 대화" })).toBeDisabled();
    expect(textbox).toBeDisabled();
  });

  it("requires fresh domain entry after a provider policy denial", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      return errorResponse(403, "provider_not_allowed", "private provider policy detail");
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);
    await user.type(screen.getByRole("textbox", { name: "질문" }), "공급자 정책 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("현재 데이터 정책이 선택한 외부 생성 서비스를 허용하지 않습니다.");
    expect(alert).not.toHaveTextContent("private provider policy detail");
    expect(within(alert).getByRole("link", { name: "도메인 선택으로 돌아가기" })).toHaveAttribute(
      "href",
      "/workshop/rag/search",
    );
    expect(within(alert).queryByRole("button", { name: "같은 질문 다시 시도" })).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "질문" })).toBeDisabled();
  });

  it("treats a real deployment-not-ready envelope as a safe transient failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      return errorResponse(503, "deployment_not_ready", "private health probe detail");
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);
    await user.type(screen.getByRole("textbox", { name: "질문" }), "모델 준비 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("선택한 생성 실행이 준비되지 않았습니다.");
    expect(alert).not.toHaveTextContent("private health probe detail");
    expect(within(alert).getByRole("button", { name: "같은 질문 다시 시도" })).toBeVisible();
  });

  it("fails closed on a changed connection and requires a fresh domain entry", async () => {
    let searchAttempts = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      searchAttempts += 1;
      return errorResponse(409, "domain_connection_changed", "private replacement connection id");
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);
    const textbox = screen.getByRole("textbox", { name: "질문" });
    await user.type(textbox, "연결 변경 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("최신 연결과 검색 범위를 다시 불러오려면 도메인을 다시 선택해 주세요.");
    expect(alert).not.toHaveTextContent("private replacement connection id");
    expect(within(alert).getByRole("link", { name: "도메인 선택으로 돌아가기" })).toHaveAttribute(
      "href",
      "/workshop/rag/search",
    );
    expect(within(alert).queryByRole("button", { name: "같은 질문 다시 시도" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "새 대화" })).toBeDisabled();
    expect(textbox).toBeDisabled();
    fireEvent.submit(textbox.closest("form") as HTMLFormElement);
    expect(searchAttempts).toBe(1);
  });

  it("does not present a missing generative execution as a successful answer", async () => {
    const result = searchResult(1);
    result.generation = {
      ...result.generation,
      status: "not_requested",
      text: null,
      citations: [],
      turn_id: null,
      validation_token: null,
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      return jsonResponse(result);
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);
    await user.type(screen.getByRole("textbox", { name: "질문" }), "실행 상태 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("생성 답변을 실행하지 못했습니다.");
    expect(screen.queryByText("답변 1")).not.toBeInTheDocument();
  });

  it("excludes an unverified assistant turn and its question from later history", async () => {
    const bodies: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/folders")) return jsonResponse([]);
      bodies.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
      const result = searchResult(bodies.length);
      if (bodies.length === 1) {
        result.generation = {
          ...result.generation,
          status: "citation_validation_failed",
          text: null,
          citations: [],
          turn_id: null,
          validation_token: null,
        };
      }
      return jsonResponse(result);
    }));
    const user = userEvent.setup();
    render(<ConversationPage domain={domain()} />);
    const textbox = screen.getByRole("textbox", { name: "질문" });
    await user.type(textbox, "검증 실패 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    expect(await screen.findByText(/인용을 검증하지 못해/)).toBeVisible();
    await user.type(textbox, "다음 질문");
    await user.click(screen.getByRole("button", { name: "질문 보내기" }));
    await screen.findByText("답변 2");

    expect(bodies[1]).not.toHaveProperty("history");
  });
});

function domain(overrides: Partial<Domain> = {}): Domain {
  const base: Domain = {
    id: "domain-1",
    slug: "asset-management",
    display_name: "자산운용",
    description: "운용 규정과 리서치",
    active: true,
    ready: true,
    connection_version: { id: "connection-1", version: 2 },
    readiness: { search_ready: true, answer_ready: true, service_ready: true, reason_codes: [] },
    workspace_options: [
      { id: "workspace-1", name: "회사 규정", kind: "company", expires_at: null },
      { id: "workspace-2", name: "개인 연구", kind: "personal", expires_at: null },
    ],
    generation_execution_preview: {
      deployment_name: "사내 답변",
      model_name: "Korean LLM",
      model_version: 3,
      provider: "local_openai_compatible",
      disclosure_version: "on-premise-generation-v1",
      location: "on_premise",
      external_transfer: false,
      disclosure: "질문과 근거는 승인된 사내 환경에서 처리됩니다.",
    },
  };
  return { ...base, ...overrides };
}

function externalDomain(): Domain {
  return domain({
    generation_execution_preview: {
      deployment_name: "외부 답변",
      model_name: "외부 모델",
      model_version: 2,
      provider: "openai_responses",
      disclosure_version: "external-generation-v1",
      location: "external",
      external_transfer: true,
      disclosure: "현재 질문과 제한된 이전 대화, 선별 근거가 외부 API로 전송됩니다.",
    },
  });
}

function searchResult(turn: number): DomainSearchResult {
  return {
    status: "supported",
    answer: evidence(),
    conflict_state: "none",
    conflicts: [],
    warnings: [],
    related_sources: [],
    configuration_version: { configuration_id: "configuration-1", version_id: "configuration-version-1", version: 4 },
    experimental: false,
    resolved_query: `질문 ${turn}`,
    generation: {
      status: "answered",
      text: `답변 ${turn}`,
      citations: [{ claim_index: 0, evidence_ids: ["evidence-1"] }],
      reason_codes: [],
      turn_id: `turn-${turn}`,
      validation_token: `signed-${turn}`,
      execution: null,
    },
    domain_context: {
      domain_id: "domain-1",
      connection_version_id: "connection-1",
      workspace_ids: ["workspace-1", "workspace-2"],
      folder_ids: [],
    },
    selected_scope: null,
  };
}

function selectedDocument() {
  return { active_version_id: "asset-version-current", folder_id: null, id: "document-1", job_id: null, latest_version: 3, latest_version_id: "asset-version-current", metadata_revision: 1, name: "운용 규정.md", status: "ready" as const, workspace_id: "workspace-1" };
}

function selectedScope(): NonNullable<DomainSearchResult["selected_scope"]> {
  return { identities: [{ document_id: "document-1", asset_version_id: "asset-version-used", projection_id: "projection-1", index_build_id: "build-1" }], fingerprint: "scope-fingerprint" };
}

function libraryPage() {
  return { ancestors: [], documents: [selectedDocument()], folder: null, folders: [], next_document_cursor: null, next_folder_cursor: null, workspace: domain().workspace_options[0] };
}

function evidence(): Evidence {
  return {
    excerpt: "환매 요청은 3일 전에 접수합니다.",
    source: {
      document_id: "document-1",
      asset_version_id: "asset-version-1",
      asset_version_number: 4,
      workspace_id: "workspace-1",
      folder_id: null,
      projection_id: "projection-1",
      chunk_id: "chunk-1",
      evidence_unit_id: "evidence-1",
      element_id: "element-1",
      title: "환매 규정",
      media_type: "text/plain",
      section_path: ["환매"],
      location: { element_id: "element-1", page: null, char_start: 0, char_end: 16, bbox: null, source_kind: "normalized_text", source_part: null, image_sha256: null, table_cell: null },
    },
    highlights: [{ kind: "keyword", evidence_unit_id: "evidence-1", text: "환매", char_start: 0, char_end: 2, page: null, bbox: null, score: null, warnings: [] }],
    keyword_coverage: 1,
    semantic_score: 0.9,
    warnings: [],
  };
}

function normalizedText() {
  return {
    document_id: "document-1",
    asset_version_id: "asset-version-1",
    asset_version_number: 4,
    workspace_id: "workspace-1",
    folder_id: null,
    projection_id: "projection-1",
    title: "환매 규정",
    media_type: "text/plain",
    parser_name: "plain",
    parser_version: "1",
    elements: [{ id: "element-1", ordinal: 0, kind: "paragraph", text: "환매 요청은 3일 전에 접수합니다.", section_path: ["환매"], location: { element_id: "element-1", page: null, char_start: 0, char_end: 18, bbox: null, source_kind: "normalized_text", source_part: null, image_sha256: null, table_cell: null }, confidence: 1, evidence_eligible: true, warnings: [] }],
  };
}

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function errorResponse(status: number, code: string, message: string) {
  return jsonResponse({ error: { code, message, correlation_id: "correlation-1" } }, status);
}
