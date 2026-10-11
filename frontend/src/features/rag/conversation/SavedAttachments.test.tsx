import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";
import type { Domain } from "../domains/api";
import { ConversationPage } from "./ConversationPage";

const domain: Domain = {
  id: "domain", slug: "example", display_name: "합성 자료", description: "",
  active: true, ready: false, connection_version: { id: "connection", version: 1 },
  readiness: { search_ready: true, answer_ready: false, service_ready: false, reason_codes: ["deployment_not_ready"] },
  workspace_options: [{ id: "company", name: "합성 회사 자료", kind: "company", expires_at: null }],
  generation_execution_preview: null,
};
const summary = { id: "session-1", title: "저장된 합성 대화", revision: 1, created_at: "2026-10-08", updated_at: "2026-10-08" };
const turn = {
  id: "turn", request_id: "request", sequence: 1, status: "failed", query: "합성 질문",
  response: null, error_code: "provider_timeout", redacted: false, execution_terminated: true,
  segment: 1, created_at: summary.created_at, updated_at: summary.updated_at,
  request_scope: { connection_version_id: "connection", workspace_ids: ["company"], folder_ids: [], document_ids: null },
};
const attachment = {
  id: "attachment", status: "stored", error_code: "attachment_outside_generation_scope", excluded_at: null,
  document: { id: "private-file", name: "synthetic.pdf", workspace_id: "personal", status: "pending" },
};
const json = (value: unknown) => new Response(JSON.stringify(value), { headers: { "content-type": "application/json" } });
afterEach(() => { vi.unstubAllGlobals(); window.history.replaceState(null, "", "/"); });

it("restores saved attachment status without another upload or a generation-ready domain", async () => {
  window.history.replaceState(null, "", "/?conversation=session-1");
  const methods: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input); methods.push(init?.method ?? "GET");
    if (path.endsWith("/folders")) return json([]);
    if (path.endsWith("/conversations")) return json([summary]);
    if (path.endsWith("/attachment-options")) return json({ workspaces: [{ id: "personal", name: "개인 공간" }] });
    if (path.endsWith("/attachments")) return json([attachment]);
    return json({ ...summary, turns: [turn] });
  }));
  render(<ConversationPage domain={domain} />);
  expect(await screen.findByText("synthetic.pdf · 저장됨 · 현재 답변에 사용 불가")).toBeVisible();
  expect(screen.getByText("현재 대화의 검색·생성 범위에 포함되지 않은 개인 파일입니다.")).toBeVisible();
  expect(screen.queryByRole("button", { name: "질문에 추가" })).not.toBeInTheDocument();
  expect(methods.every(method => method === "GET")).toBe(true);
});

it("ignores attachment rows returned after selecting another conversation", async () => {
  window.history.replaceState(null, "", "/?conversation=session-1");
  const other = { ...summary, id: "session-2", title: "다른 저장 대화" };
  let resolveOld: ((response: Response) => void) | undefined;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/folders")) return json([]);
    if (path.endsWith("/conversations")) return json([summary, other]);
    if (path.endsWith("/session-1/attachments")) return new Promise<Response>(resolve => { resolveOld = resolve; });
    if (path.endsWith("/attachments")) return json([]);
    if (path.endsWith("/attachment-options")) return json({ workspaces: [{ id: "personal", name: "개인 공간" }] });
    return json({ ...(path.endsWith("/session-2") ? other : summary), turns: [turn] });
  }));
  render(<ConversationPage domain={domain} />);
  await screen.findByText("합성 질문");
  await waitFor(() => expect(resolveOld).toBeDefined());
  fireEvent.click(screen.getByRole("button", { name: "다른 저장 대화" }));
  await screen.findByRole("heading", { name: "다른 저장 대화" });
  await act(async () => { resolveOld!(json([attachment])); });
  expect(screen.queryByText(/synthetic.pdf/)).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "PC 파일 첨부" })).not.toBeInTheDocument();
});

it("keeps the attachment area hidden when the restored session has no visible files", async () => {
  window.history.replaceState(null, "", "/?conversation=session-1");
  let lookedUp = false;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/folders")) return json([]);
    if (path.endsWith("/conversations")) return json([summary]);
    if (path.endsWith("/attachments")) { lookedUp = true; return json([{ ...attachment, excluded_at: "2026-10-08" }]); }
    return json({ ...summary, turns: [turn] });
  }));
  render(<ConversationPage domain={domain} />);
  await screen.findByText("합성 질문");
  await waitFor(() => expect(lookedUp).toBe(true));
  expect(screen.queryByText(/synthetic.pdf/)).not.toBeInTheDocument();
  expect(screen.queryByRole("region", { name: "PC 파일 첨부" })).not.toBeInTheDocument();
});

it("shows the safe existing attachment error when the restore lookup fails", async () => {
  window.history.replaceState(null, "", "/?conversation=session-1");
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/folders")) return json([]);
    if (path.endsWith("/conversations")) return json([summary]);
    if (path.endsWith("/attachments")) return new Response("synthetic private detail", { status: 500 });
    if (path.endsWith("/attachment-options")) return json({ workspaces: [{ id: "personal", name: "개인 공간" }] });
    return json({ ...summary, turns: [turn] });
  }));
  render(<ConversationPage domain={domain} />);
  expect(await screen.findByText("첨부 처리 상태를 확인하지 못했습니다. 대화를 다시 열어 확인해 주세요.")).toBeVisible();
  expect(screen.queryByText(/synthetic private detail/)).not.toBeInTheDocument();
});
