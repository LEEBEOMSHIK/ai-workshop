import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import type { Domain } from "../domains/api";
import { ConversationPage } from "./ConversationPage";
import type { ConversationDetail } from "./sessions-api";

const domain: Domain = { id: "domain", slug: "example", display_name: "자료 대화", description: "", active: true, ready: true,
  connection_version: { id: "connection", version: 1 }, readiness: { search_ready: true, answer_ready: true, service_ready: true, reason_codes: [] },
  workspace_options: [{ id: "workspace", name: "자료", kind: "personal", expires_at: null }],
  generation_execution_preview: { deployment_name: "local", model_name: "local", model_version: 1, provider: "local_openai_compatible", disclosure_version: "v1", location: "local", external_transfer: false, disclosure: "로컬 처리" } };
const json = (value: unknown) => Response.json(value);
afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

it.each([false, true])("retains only same-screen POST input after GET completes first (leave screen: %s)", async (leaveScreen) => {
  let releasePost!: (response: Response) => void;
  let detail!: ConversationDetail;
  const post = new Promise<Response>(resolve => { releasePost = resolve; });
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (path.endsWith("/folders") || path.endsWith("/conversations")) return json([]);
    if (path.endsWith("/start")) {
      const request = JSON.parse(String(init?.body));
      detail = { id: "session", revision: 2, title: "합성 대화", title_origin: "auto", legacy_state: "active",
        created_at: "2026-10-16", updated_at: "2026-10-16", turns: [{
          id: "turn", request_id: request.request_id, sequence: 1, segment: 1, status: "completed", query: request.query,
          redacted: false, error_code: null, execution_terminated: true, created_at: "2026-10-16", updated_at: "2026-10-16",
          request_scope: { connection_version_id: "connection", workspace_ids: ["workspace"], folder_ids: [], document_ids: null },
          response: { status: "supported", answer: null, conflict_state: "none", conflicts: [], warnings: [], related_sources: [], experimental: false,
            resolved_query: request.query, selected_scope: null, configuration_version: { configuration_id: "config", version_id: "version", version: 1 },
            domain_context: { domain_id: "domain", connection_version_id: "connection", workspace_ids: ["workspace"], folder_ids: [] },
            generation: { status: "answered", text: "합성 답변", citations: [], reason_codes: [], turn_id: "turn", validation_token: null, execution: null },
            diagnostics: { candidate_scope: "returned_hits", candidates: [], stages_ms: {}, min_keyword_coverage: 0.5, min_semantic_score: 0.9 },
          },
        }] };
      return post;
    }
    if (path.includes("/starts/")) return json(detail);
    throw new Error(`Unexpected route ${path}`);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]} />);
  fireEvent.change(screen.getByRole("textbox", { name: "질문" }), { target: { value: "합성 질문" } });
  fireEvent.click(screen.getByRole("button", { name: "질문 보내기" }));
  await screen.findByRole("heading", { name: "합성 대화" });
  fireEvent.click(screen.getByText(/검색 근거·유사도/));
  fireEvent.click(screen.getByText("LLM 입력 확인"));
  expect(screen.getByText(/이 결과에는 최종 요청 본문 기록이 없습니다/)).toBeVisible();
  if (leaveScreen) fireEvent.click(screen.getByRole("button", { name: "새 대화" }));
  const fresh = structuredClone(detail);
  fresh.turns[0].observation_complete = true;
  fresh.turns[0].response!.diagnostics!.generation_input = {
    status: "response_received", provider: "local_openai_compatible", dialect: "chat_completions", model: "합성 모델", model_version: 1,
    prompt_ref: "rag-answer-v3", profile_version: 1, request_json: null, content_status: "omitted_size_limit",
    body_characters: 300000, body_bytes: 300000, capture_limit_characters: 100000, sha256: "a".repeat(64),
    max_output_tokens: 128, evidence_budget: null, provider_truncation: "unknown",
  };
  await act(async () => { releasePost(json(fresh)); });
  if (leaveScreen) {
    expect(screen.queryByText("HTTP 응답 수신 확인")).not.toBeInTheDocument();
    expect(screen.queryByText("합성 답변")).not.toBeInTheDocument();
  } else {
    await waitFor(() => expect(screen.getByText("HTTP 응답 수신 확인")).toBeVisible());
    expect(screen.getAllByText("합성 답변")).toHaveLength(1);
  }
});
