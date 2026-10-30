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

it("polls a restored running conversation without losing the next draft and stops at termination", async () => {
  window.history.replaceState(null, "", "/?conversation=session");
  let current = running;
  let reads = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/session")) { reads++; return Response.json(current); }
    if (path.endsWith("/conversations")) return Response.json([current]);
    return Response.json([]);
  }));
  const view = render(<ConversationPage domain={domain} />);
  await screen.findByText("공개 합성 질문");
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  // A fresh selection schedules its poll under this clock.
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "진행 중인 대화" })));
  const question = screen.getByRole("textbox", { name: "질문" });
  fireEvent.change(question, { target: { value: "작성해 둔 다음 질문" } });
  expect(question).toBeEnabled();
  expect(screen.getByRole("button", { name: "질문 보내기" })).toBeDisabled();
  current = finished;
  const before = reads;
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(reads).toBeGreaterThan(before);
  expect(question).toHaveValue("작성해 둔 다음 질문");
  expect(screen.getByRole("button", { name: "질문 보내기" })).toBeEnabled();
  const stopped = reads;
  await act(async () => vi.advanceTimersByTimeAsync(6000));
  expect(reads).toBe(stopped);
  view.unmount();
});

it.each(["new", "unmount"])("keeps a first question in the background after %s while acceptance is pending", async leave => {
  let resolveStart!: (value: Response) => void;
  const cancellations: string[] = [];
  let preference: string | null = null;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/start")) {
      preference = new Headers(init?.headers).get("Prefer");
      return new Promise<Response>(resolve => { resolveStart = resolve; });
    }
    if (path.includes("/starts/")) return Response.json({ error: { code: "not_found", message: "synthetic" } }, { status: 404 });
    if (path.endsWith("/cancel")) { cancellations.push(path); return Response.json(finished); }
    return Response.json([]);
  }));
  const view = render(<ConversationPage domain={domain} initialWorkspaceIds={["workspace"]} />);
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
  fireEvent.change(screen.getByRole("textbox", { name: "질문" }), { target: { value: "공개 합성 질문" } });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "질문 보내기" })));
  expect(screen.getByRole("textbox", { name: "질문" })).toBeEnabled();
  expect(preference).toBe("respond-async");
  if (leave === "new") {
    fireEvent.click(screen.getByRole("button", { name: "새 대화" }));
    fireEvent.change(screen.getByRole("textbox", { name: "질문" }), { target: { value: "다른 대화 초안" } });
  } else view.unmount();
  await act(async () => resolveStart(Response.json(running, { status: 202 })));
  await act(async () => vi.advanceTimersByTimeAsync(4000));
  expect(cancellations).toEqual([]);
  if (leave === "new") {
    expect(screen.getByRole("textbox", { name: "질문" })).toHaveValue("다른 대화 초안");
    expect(screen.queryByRole("heading", { name: running.title })).not.toBeInTheDocument();
    view.unmount();
  }
});

it("discards a late status response after switching to a new conversation", async () => {
  window.history.replaceState(null, "", "/?conversation=session");
  let resolvePoll!: (value: Response) => void;
  let hold = false;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
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
  fireEvent.click(screen.getByRole("button", { name: "새 대화" }));
  fireEvent.change(screen.getByRole("textbox", { name: "질문" }), { target: { value: "새 화면 초안" } });
  await act(async () => resolvePoll(Response.json(finished)));
  expect(screen.queryByRole("heading", { name: running.title })).not.toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "질문" })).toHaveValue("새 화면 초안");
  view.unmount();
});
