import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import type { Domain } from "../domains/api";
import { ConversationPage } from "./ConversationPage";
import type { ConversationDetail, ConversationTurn, TurnRequest } from "./sessions-api";

const domain: Domain = {
  id: "domain", slug: "example", display_name: "자료 대화", description: "", active: true, ready: true,
  connection_version: { id: "connection", version: 1 },
  readiness: { search_ready: true, answer_ready: true, service_ready: true, reason_codes: [] },
  workspace_options: [{ id: "workspace", name: "자료", kind: "personal", expires_at: null }],
  generation_execution_preview: { deployment_name: "local", model_name: "local", model_version: 1,
    provider: "local_openai_compatible", disclosure_version: "v1", location: "local",
    external_transfer: false, disclosure: "로컬 처리" },
};

function savedConversation(overrides: Partial<ConversationTurn> = {}): ConversationDetail {
  return {
    id: "session", title: "저장된 대화", title_origin: "auto", legacy_state: "active", revision: 3,
    created_at: "2026-10-21", updated_at: "2026-10-21",
    turns: [{ id: "turn", request_id: "previous-request", sequence: 1, segment: 1, status: "failed",
      query: "이전 질문", response: null, error_code: "provider_termination_unconfirmed",
      execution_terminated: false, redacted: false, created_at: "2026-10-21", updated_at: "2026-10-21",
      request_scope: { connection_version_id: "connection", workspace_ids: ["workspace"],
        folder_ids: [], document_ids: null }, ...overrides }],
  };
}

function savedApi(current: () => ConversationDetail, submit?: (request: TurnRequest) => Response) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/folders") || path.endsWith("/attachments")) return Response.json([]);
    if (path.endsWith("/conversations")) return Response.json([current()]);
    if (path.endsWith("/session")) return Response.json(current());
    if (path.endsWith("/turns") && init?.method === "POST" && submit) {
      return submit(JSON.parse(String(init.body)) as TurnRequest);
    }
    throw new Error(`Unexpected synthetic request: ${path}`);
  }));
  window.history.replaceState(null, "", "/?conversation=session");
}

afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

it.each([
  { status: "failed", error_code: "provider_termination_unconfirmed" },
  { status: "interrupted", error_code: "provider_termination_unconfirmed" },
  { status: "interrupted", error_code: "conversation_termination_unconfirmed" },
] as const)("restores $status/$error_code as blocked and refreshes without losing the draft", async state => {
  let current = savedConversation(state);
  const posts: TurnRequest[] = [];
  savedApi(() => current, request => {
    posts.push(request);
    current = { ...current, revision: 5, turns: [...current.turns, {
      ...current.turns[0], id: "next-turn", request_id: request.request_id, sequence: 2,
      query: request.query, execution_terminated: true, status: "failed", error_code: "provider_timeout",
    }] };
    return Response.json(current);
  });
  render(<ConversationPage domain={domain} />);
  await screen.findByText("이전 질문");
  const question = screen.getByRole("textbox", { name: "질문" });
  fireEvent.change(question, { target: { value: "보존할 다음 질문" } });
  expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
  expect(screen.getByText(/이전 요청의 실행 종료를 확인하지 못했습니다/)).toBeVisible();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "상태 새로고침" })));
  expect(question).toHaveValue("보존할 다음 질문");
  expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
  expect(posts).toHaveLength(0);

  // Only an authoritative response changes the flag; the UI never clears it.
  current = { ...current, revision: 4, turns: [{ ...current.turns[0], execution_terminated: true,
    error_code: state.status === "interrupted" ? "conversation_execution_interrupted" : "provider_timeout" }] };
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "상태 새로고침" })));
  expect(screen.queryByRole("button", { name: "상태 새로고침" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "질문 보내기" })).toBeEnabled();
  expect(question).toHaveValue("보존할 다음 질문");
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "질문 보내기" })));
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0]).toMatchObject({ query: "보존할 다음 질문", expected_revision: 4 });
  expect(posts[0].request_id).not.toBe("previous-request");
  expect(await screen.findByText("보존할 다음 질문")).toBeVisible();
});

it.each(["provider_termination_unconfirmed", "conversation_termination_unconfirmed"])("blocks a stale retry action after refresh reveals %s", async error_code => {
  let current = savedConversation({ error_code: "provider_timeout", execution_terminated: true });
  const posts: TurnRequest[] = [];
  savedApi(() => current, request => { posts.push(request); throw new TypeError("Synthetic lost response"); });
  render(<ConversationPage domain={domain} />);
  await screen.findByText("이전 질문");
  fireEvent.change(screen.getByRole("textbox", { name: "질문" }), { target: { value: "응답을 놓친 질문" } });
  fireEvent.click(screen.getByRole("button", { name: "질문 보내기" }));
  await screen.findByRole("button", { name: "같은 질문 다시 시도" });
  expect(posts).toHaveLength(1);
  current = { ...current, revision: 4, turns: [...current.turns, {
    ...savedConversation({ status: "interrupted", error_code }).turns[0], id: "pending-turn", sequence: 2,
    request_id: posts[0].request_id, query: posts[0].query,
  }] };
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "대화 목록 새로고침" })));
  expect(screen.getByRole("button", { name: "같은 질문 다시 시도" })).toBeDisabled();
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "같은 질문 다시 시도" })));
  expect(posts).toHaveLength(1);
});

it.each([
  { status: "failed", execution_terminated: true, error_code: "provider_timeout" },
  { status: "cancelled", execution_terminated: true, error_code: "conversation_cancelled" },
  { status: "failed", execution_terminated: false, error_code: "conversation_execution_failed" },
  { status: "interrupted", execution_terminated: false, error_code: "conversation_execution_interrupted" },
] as const)("preserves existing next-question behavior for $status/$error_code", async state => {
  savedApi(() => savedConversation(state));
  render(<ConversationPage domain={domain} />);
  await screen.findByText("이전 질문");
  fireEvent.change(screen.getByRole("textbox", { name: "질문" }), { target: { value: "다음 질문" } });
  expect(screen.getByRole("button", { name: "질문 보내기" })).toBeEnabled();
  expect(screen.queryByRole("button", { name: "상태 새로고침" })).not.toBeInTheDocument();
});
