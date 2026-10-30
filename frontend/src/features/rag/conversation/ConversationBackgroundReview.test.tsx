import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import type { Domain } from "../domains/api";
import { ConversationPage } from "./ConversationPage";
import type { ConversationDetail } from "./sessions-api";

const domain: Domain = {
  id: "domain", slug: "example", display_name: "자료 대화", description: "", active: true, ready: true,
  connection_version: { id: "connection", version: 1 },
  readiness: { search_ready: true, answer_ready: true, service_ready: true, reason_codes: [] },
  workspace_options: [{ id: "workspace", name: "자료", kind: "personal", expires_at: null }],
  generation_execution_preview: { deployment_name: "local", model_name: "local", model_version: 1,
    provider: "local_openai_compatible", disclosure_version: "v1", location: "local",
    external_transfer: false, disclosure: "로컬 처리" },
};
const running: ConversationDetail = {
  id: "session", title: "진행 중인 대화", title_origin: "auto", legacy_state: "active", revision: 2,
  created_at: "2026-10-26", updated_at: "2026-10-26",
  turns: [{ id: "turn", request_id: "request", sequence: 1, segment: 1, status: "running",
    query: "공개 합성 질문", response: null, error_code: null, redacted: false, execution_terminated: false,
    created_at: "2026-10-26", updated_at: "2026-10-26",
    request_scope: { connection_version_id: "connection", workspace_ids: ["workspace"], folder_ids: [], document_ids: null } }],
};
const finished: ConversationDetail = { ...running, revision: 3, turns: [{ ...running.turns[0],
  status: "failed", execution_terminated: true, error_code: "provider_timeout" }] };

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); window.history.replaceState(null, "", "/"); });

it.each(["rename", "cancel"])("does not overwrite a newer %s result with an in-flight status snapshot", async operation => {
  window.history.replaceState(null, "", "/?conversation=session");
  let resolvePoll!: (value: Response) => void;
  let hold = false;
  const newer: ConversationDetail = operation === "rename"
    ? { ...running, revision: 4, title: "새 제목", title_origin: "manual" }
    : { ...finished, revision: 4, turns: [{ ...finished.turns[0], status: "cancelled", execution_terminated: false }] };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (init?.method === "PATCH" || path.endsWith("/cancel")) return Response.json(newer);
    if (path.endsWith("/session")) return hold ? new Promise<Response>(resolve => { resolvePoll = resolve; }) : Response.json(running);
    if (path.endsWith("/conversations")) return Response.json([running]);
    return Response.json([]);
  }));
  const view = render(<ConversationPage domain={domain} />);
  await screen.findByText("공개 합성 질문");
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: running.title })));
  hold = true;
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(resolvePoll).toBeDefined();
  if (operation === "rename") {
    fireEvent.click(screen.getByRole("button", { name: "대화 이름 변경" }));
    fireEvent.change(screen.getByRole("textbox", { name: "대화 제목" }), { target: { value: newer.title } });
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "제목 저장" })));
  } else await act(async () => fireEvent.click(screen.getByRole("button", { name: "답변 취소" })));
  await act(async () => resolvePoll(Response.json(running)));
  if (operation === "rename") expect(screen.getByRole("heading", { name: newer.title })).toBeVisible();
  else expect(screen.queryByRole("button", { name: "답변 취소" })).not.toBeInTheDocument();
  view.unmount();
});

it("clears the dirty title and rejects an equally revisioned late first POST after redaction", async () => {
  let resolvePost!: (value: Response) => void;
  const redacted: ConversationDetail = { ...running, title: "접근할 수 없는 대화", turns: [{
    ...running.turns[0], query: "", redacted: true, request_scope: null,
  }] };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/start")) return new Promise<Response>(resolve => { resolvePost = resolve; });
    if (path.includes("/starts/")) return Response.json(running);
    if (path.endsWith("/session")) return Response.json(redacted);
    return Response.json([]);
  }));
  const view = render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]} />);
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  fireEvent.change(screen.getByRole("textbox", { name: "질문" }), { target: { value: "공개 합성 질문" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "질문 보내기" })));
  fireEvent.click(screen.getByRole("button", { name: "대화 이름 변경" }));
  fireEvent.change(screen.getByRole("textbox", { name: "대화 제목" }), { target: { value: "공개 합성 편집 캐시" } });
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  const retainedEditor = screen.queryByRole("textbox", { name: "대화 제목" });
  const staleTitleRetained = retainedEditor instanceof HTMLInputElement && retainedEditor.value === "공개 합성 편집 캐시";
  await act(async () => resolvePost(Response.json(running, { status: 202 })));
  expect(staleTitleRetained).toBe(false);
  expect(screen.getByRole("heading", { name: redacted.title })).toBeVisible();
  expect(screen.queryByText("공개 합성 질문")).not.toBeInTheDocument();
  view.unmount();
});

it("keeps a newly accepted next turn when an earlier poll returns late", async () => {
  window.history.replaceState(null, "", "/?conversation=session");
  let resolvePoll!: (value: Response) => void;
  let holdNext = false;
  let current = running;
  const next: ConversationDetail = { ...finished, revision: 5, turns: [...finished.turns, {
    ...running.turns[0], id: "turn-two", request_id: "request-two", sequence: 2, query: "두 번째 공개 질문",
  }] };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/turns") && init?.method === "POST") return Response.json(next, { status: 202 });
    if (path.endsWith("/session")) {
      if (holdNext) { holdNext = false; return new Promise<Response>(resolve => { resolvePoll = resolve; }); }
      return Response.json(current);
    }
    if (path.endsWith("/conversations")) return Response.json([current]);
    return Response.json([]);
  }));
  const view = render(<ConversationPage domain={domain} />);
  await screen.findByText("공개 합성 질문");
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: running.title })));
  holdNext = true;
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(resolvePoll).toBeDefined();
  current = finished;
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "상태 새로고침" })));
  fireEvent.change(screen.getByRole("textbox", { name: "질문" }), { target: { value: "두 번째 공개 질문" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "질문 보내기" })));
  expect(screen.getByText("두 번째 공개 질문")).toBeVisible();
  await act(async () => resolvePoll(Response.json(running)));
  expect(screen.getByText("두 번째 공개 질문")).toBeVisible();
  expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
  view.unmount();
});
