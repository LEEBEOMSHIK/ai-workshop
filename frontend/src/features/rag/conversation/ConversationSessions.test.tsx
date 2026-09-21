import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import { ConversationPage } from "./ConversationPage";
import type { Domain } from "../domains/api";

const domain: Domain = { id: "domain", slug: "example", display_name: "자료 대화", description: "", active: true, ready: true, connection_version: {id: "connection", version: 1}, readiness: {search_ready: true, answer_ready: true, service_ready: true, reason_codes: []}, workspace_options: [{id: "workspace", name: "자료", kind: "personal", expires_at: null}], generation_execution_preview: {deployment_name: "local", model_name: "local", model_version: 1, provider: "local_openai_compatible", disclosure_version: "v1", location: "local", external_transfer: false, disclosure: "로컬 처리"} };
const summary = {id: "session-1", title: "저장된 대화", revision: 1, created_at: "2026-09-21T00:00:00Z", updated_at: "2026-09-21T00:00:00Z"};
const scope = {connection_version_id: "connection", workspace_ids: ["workspace"], folder_ids: [], document_ids: null};
const turn = {id: "turn-1", request_id: "request-1", sequence: 1, status: "failed", query: "이전 질문", response: null, request_scope: scope, segment: 1, error_code: "provider_timeout", redacted: false, execution_terminated: true, created_at: summary.created_at, updated_at: summary.updated_at};
const json = (value: unknown) => new Response(JSON.stringify(value), {headers: {"content-type": "application/json"}});
afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

it("restores the URL-selected server conversation and preserves it on new chat", async () => {
  window.history.replaceState(null, "", "/?conversation=session-1");
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => {
    if (String(url).endsWith("/folders")) return json([]);
    if (String(url).endsWith("/conversations")) return json([summary]);
    return json({...summary, turns: [turn]});
  }));
  render(<ConversationPage domain={domain} />);
  expect(await screen.findByText("이전 질문")).toBeVisible();
  expect(screen.getByText(/응답 시간이 초과/)).toBeVisible();
  fireEvent.click(screen.getByRole("button", {name: "새 대화"}));
  expect(screen.queryByText("이전 질문")).not.toBeInTheDocument();
  expect(screen.getByRole("button", {name: "저장된 대화"})).toBeVisible();
});

it("renames and deletes the selected session using the current server revision", async () => {
  window.history.replaceState(null, "", "/?conversation=session-1");
  const mutations: Array<{path: string; init: RequestInit}> = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (path.endsWith("/folders")) return json([]);
    if (path.endsWith("/conversations")) return json([summary]);
    if (init?.method === "PATCH") { mutations.push({path, init}); return json({...summary, title: "새 제목", revision: 2, turns: [turn]}); }
    if (init?.method === "DELETE") { mutations.push({path, init}); return new Response(null, {status: 204}); }
    return json({...summary, turns: [turn]});
  }));
  render(<ConversationPage domain={domain} />);
  await screen.findByText("이전 질문");
  fireEvent.click(screen.getByRole("button", {name: "대화 이름 변경"}));
  fireEvent.change(screen.getByRole("textbox", {name: "대화 제목"}), {target: {value: "새 제목"}});
  fireEvent.click(screen.getByRole("button", {name: "제목 저장"}));
  await screen.findByRole("button", {name: "새 제목"});
  expect(JSON.parse(String(mutations[0].init.body))).toEqual({title: "새 제목", expected_revision: 1});
  fireEvent.click(screen.getByRole("button", {name: "대화 삭제"}));
  fireEvent.click(screen.getByRole("button", {name: "삭제 확인"}));
  await waitFor(() => expect(screen.queryByText("이전 질문")).not.toBeInTheDocument());
  expect(mutations[1].path).toContain("expected_revision=2");
  expect(new URL(window.location.href).searchParams.has("conversation")).toBe(false);
});

it("reuses the request ID after a transport failure and never sends local response text", async () => {
  const requests: Record<string, unknown>[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url);
    if (path.endsWith("/folders")) return json([]);
    if (path.endsWith("/conversations")) return json(init?.method === "POST" ? {...summary, turns: []} : []);
    if (path.endsWith("/turns")) {
      requests.push(JSON.parse(String(init?.body)));
      if (requests.length === 1) throw new TypeError("Network error");
      return json({...summary, revision: 2, turns: [{...turn, query: "새 질문"}]});
    }
    throw new Error(`Unexpected ${path}`);
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]} />);
  fireEvent.change(screen.getByRole("textbox", {name: "질문"}), {target: {value: "새 질문"}});
  fireEvent.click(screen.getByRole("button", {name: "질문 보내기"}));
  fireEvent.click(await screen.findByRole("button", {name: "같은 질문 다시 시도"}));
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[1]).toEqual(requests[0]);
  expect(requests[1]).not.toHaveProperty("history");
  expect(requests[1]).not.toHaveProperty("response");
});

it("hides redacted turns and ignores a late detail after switching sessions", async () => {
  let resolveOld!: (response: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => {
    const path = String(url);
    if (path.endsWith("/folders")) return json([]);
    if (path.endsWith("/conversations")) return json([summary, {...summary, id: "session-2", title: "다른 대화"}]);
    if (path.endsWith("/session-1")) return new Promise<Response>(resolve => { resolveOld = resolve; });
    return json({...summary, id: "session-2", title: "다른 대화", turns: [{...turn, redacted: true, request_scope: null, query: "표시 금지"}]});
  }));
  render(<ConversationPage domain={domain} />);
  fireEvent.click(await screen.findByRole("button", {name: "저장된 대화"}));
  fireEvent.click(screen.getByRole("button", {name: "다른 대화"}));
  expect(await screen.findByText("현재 권한으로 이 대화 내용을 표시할 수 없습니다.")).toBeVisible();
  resolveOld(json({...summary, turns: [turn]}));
  await waitFor(() => expect(screen.queryByText("이전 질문")).not.toBeInTheDocument());
  expect(screen.queryByText("표시 금지")).not.toBeInTheDocument();
});

it("creates a session, sends diagnostics without client history, and cancels the server request", async () => {
  let sent: Record<string, unknown> | undefined;
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
    const path = String(url); calls.push(path);
    if (path.endsWith("/folders") || path.endsWith("/attachments")) return json([]);
    if (path.endsWith("/cancel")) return json({...summary, revision: 3, turns: [{...turn, query: "새 질문", status: "cancelled"}]});
    if (path.endsWith("/turns")) { sent = JSON.parse(String(init?.body)); return new Promise<Response>(() => {}); }
    if (path.endsWith("/conversations")) return json(init?.method === "POST" ? {...summary, turns: []} : []);
    return json({...summary, turns: []});
  }));
  render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]} />);
  fireEvent.change(screen.getByRole("textbox", {name: "질문"}), {target: {value: "새 질문"}});
  fireEvent.click(screen.getByRole("button", {name: "질문 보내기"}));
  await waitFor(() => expect(sent).toMatchObject({query: "새 질문", include_diagnostics: true, expected_revision: 1}));
  expect(sent).not.toHaveProperty("history");
  expect(sent?.request_id).toBeTruthy();
  fireEvent.click(screen.getByRole("button", {name: "답변 취소"}));
  await waitFor(() => expect(calls.some(path => path.endsWith(`/${sent?.request_id}/cancel`))).toBe(true));
  expect(await screen.findByText(/답변 생성을 취소했습니다/)).toBeVisible();
});

it("blocks another send until cancellation termination is confirmed", async () => {
  window.history.replaceState(null, "", "/?conversation=session-1");
  vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL) => {
    if (String(url).endsWith("/folders")) return json([]);
    if (String(url).endsWith("/conversations")) return json([summary]);
    return json({...summary, turns: [{...turn, status: "cancelled", execution_terminated: false}]});
  }));
  render(<ConversationPage domain={domain} />);
  expect(await screen.findByText("취소를 요청했습니다. 실행 종료 확인 중입니다.")).toBeVisible();
  fireEvent.change(screen.getByRole("textbox", {name: "질문"}), {target: {value: "다음 질문"}});
  expect(screen.getByRole("button", {name: "질문 보내기"})).toBeDisabled();
  expect(screen.getByRole("button", {name: "상태 새로고침"})).toBeVisible();
});
