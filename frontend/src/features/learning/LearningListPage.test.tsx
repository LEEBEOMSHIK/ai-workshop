import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { LearningListPage } from "./LearningListPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("LearningListPage", () => {
  it("creates a free note without experiment data or draft storage", async () => {
    const created = record({ draft: draft({ title: "새 메모", body: "첫 줄\n둘째 줄" }) });
    const requests: Array<{ path: string; init?: RequestInit }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      requests.push({ path, init });
      if (path === "/api/v1/learning/topics") return jsonResponse(topics());
      if (path === "/api/v1/rag/evaluation-runs?limit=20") return jsonResponse([]);
      if (path === "/api/v1/learning/records" && init?.method === "POST") return jsonResponse(created, 201);
      if (path.startsWith("/api/v1/learning/records")) return jsonResponse({ items: [], next_cursor: null });
      throw new Error(`Unexpected request: ${path}`);
    }));
    const onCreated = vi.fn();
    const localSet = vi.spyOn(Storage.prototype, "setItem");
    const user = userEvent.setup();
    render(<LearningListPage onCreated={onCreated} />);

    await user.click(await screen.findByRole("button", { name: "새 메모" }));
    await user.type(screen.getByRole("textbox", { name: "제목" }), "새 메모");
    await user.type(screen.getByRole("textbox", { name: "본문" }), "첫 줄\n둘째 줄");
    await user.click(screen.getByRole("button", { name: "기록 저장" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created));
    const create = requests.find((request) => request.init?.method === "POST");
    expect(JSON.parse(String(create?.init?.body))).toEqual({
      title: "새 메모",
      body: "첫 줄\n둘째 줄",
      kind: "note",
      topic_keys: [],
      domain_labels: [],
      experiment: null,
      references: [],
    });
    expect(localSet).not.toHaveBeenCalled();
  });

  it("saves a partial experiment without invented metrics and blocks duplicate submit", async () => {
    const save = deferred<Response>();
    const posts: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/learning/topics") return jsonResponse(topics());
      if (path === "/api/v1/rag/evaluation-runs?limit=20") return jsonResponse([]);
      if (path === "/api/v1/learning/records" && init?.method === "POST") {
        posts.push(init);
        return save.promise;
      }
      if (path.startsWith("/api/v1/learning/records")) return jsonResponse({ items: [], next_cursor: null });
      throw new Error(`Unexpected request: ${path}`);
    }));
    const user = userEvent.setup();
    render(<LearningListPage onCreated={vi.fn()} />);

    await user.click(await screen.findByRole("button", { name: "새 실험" }));
    await user.type(screen.getByRole("textbox", { name: "제목" }), "리랭커 실험");
    await user.type(screen.getByRole("textbox", { name: "본문" }), "실험 진행 기록");
    await user.type(screen.getByRole("textbox", { name: "목적" }), "후보 순위 비교");
    await user.selectOptions(screen.getByRole("combobox", { name: "실험 상태" }), "running");
    const submit = screen.getByRole("button", { name: "기록 저장" });
    await user.click(submit);
    await user.click(submit);

    expect(posts).toHaveLength(1);
    expect(screen.getByRole("button", { name: "저장 중…" })).toBeDisabled();
    const payload = JSON.parse(String(posts[0]?.body));
    expect(payload.body).toBe("실험 진행 기록");
    expect(payload.experiment).toMatchObject({ purpose: "후보 순위 비교", status: "running", metrics: [] });
    expect(payload.experiment).not.toHaveProperty("conclusion", "성공");
    await act(async () => save.resolve(jsonResponse(record({ draft: payload }), 201)));
  });

  it("guards reload, link, and back during a delayed POST but releases successful create navigation", async () => {
    const save = deferred<Response>();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const historyGo = vi.spyOn(window.history, "go").mockImplementation(() => undefined);
    let successfulNavigationPrevented: boolean | null = null;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/learning/topics") return jsonResponse(topics());
      if (path === "/api/v1/rag/evaluation-runs?limit=20") return jsonResponse([]);
      if (path === "/api/v1/learning/records" && init?.method === "POST") return save.promise;
      if (path.startsWith("/api/v1/learning/records")) return jsonResponse({ items: [summary("이동 대상")], next_cursor: null });
      throw new Error(`Unexpected request: ${path}`);
    }));
    const user = userEvent.setup();
    render(<LearningListPage onCreated={() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      successfulNavigationPrevented = event.defaultPrevented;
    }} />);

    await user.click(await screen.findByRole("button", { name: "새 메모" }));
    await user.type(screen.getByRole("textbox", { name: "제목" }), "저장 중 초안");
    await user.type(screen.getByRole("textbox", { name: "본문" }), "저장 중에도 보호할 본문");
    await user.click(screen.getByRole("button", { name: "기록 저장" }));
    const reload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(reload);
    expect(reload.defaultPrevented).toBe(true);
    expect(screen.getByRole("link", { name: "이동 대상" })).toBeVisible();
    expect(screen.getByRole("link", { name: "이동 대상" }).dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))).toBe(false);
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(historyGo).toHaveBeenCalledWith(1);

    await act(async () => save.resolve(jsonResponse(record(), 201)));
    await waitFor(() => expect(successfulNavigationPrevented).toBe(false));
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it.each([
    { action: "작성 닫기", expectedHeading: "새 메모" },
    { action: "새 실험", expectedHeading: "새 메모" },
  ])("keeps a dirty new draft when $action is cancelled", async ({ action, expectedHeading }) => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/learning/topics") return jsonResponse(topics());
      if (path === "/api/v1/rag/evaluation-runs?limit=20") return jsonResponse([]);
      if (path.startsWith("/api/v1/learning/records")) return jsonResponse({ items: [], next_cursor: null });
      throw new Error(`Unexpected request: ${path}`);
    }));
    const user = userEvent.setup();
    render(<LearningListPage />);

    await user.click(await screen.findByRole("button", { name: "새 메모" }));
    await user.type(screen.getByRole("textbox", { name: "제목" }), "보존할 초안");
    await user.type(screen.getByRole("textbox", { name: "본문" }), "보존할 본문");
    await user.click(screen.getByRole("button", { name: action }));

    expect(screen.getByRole("heading", { name: expectedHeading, level: 2 })).toBeVisible();
    expect(screen.getByRole("textbox", { name: "제목" })).toHaveValue("보존할 초안");
    expect(screen.getByRole("textbox", { name: "본문" })).toHaveValue("보존할 본문");
  });

  it("resets pagination on filters and ignores an older response that arrives late", async () => {
    const rag = deferred<Response>();
    const tuning = deferred<Response>();
    const paths: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      paths.push(path);
      if (path === "/api/v1/learning/topics") return jsonResponse(topics());
      if (path === "/api/v1/rag/evaluation-runs?limit=20") return jsonResponse([]);
      if (path.includes("topic_key=rag")) return rag.promise;
      if (path.includes("topic_key=fine-tuning")) return tuning.promise;
      if (path.includes("cursor=page-2")) return jsonResponse({ items: [summary("두 번째 페이지")], next_cursor: null });
      return jsonResponse({ items: [summary("첫 번째 페이지")], next_cursor: "page-2" });
    }));
    const user = userEvent.setup();
    render(<LearningListPage />);

    expect(await screen.findByText("첫 번째 페이지")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "다음 페이지" }));
    expect(await screen.findByText("두 번째 페이지")).toBeVisible();
    await user.selectOptions(screen.getByRole("combobox", { name: "주제 필터" }), "rag");
    await user.selectOptions(screen.getByRole("combobox", { name: "주제 필터" }), "fine-tuning");
    tuning.resolve(jsonResponse({ items: [summary("파인튜닝 최신")], next_cursor: null }));
    expect(await screen.findByText("파인튜닝 최신")).toBeVisible();
    rag.resolve(jsonResponse({ items: [summary("늦은 RAG 결과")], next_cursor: null }));

    await waitFor(() => expect(screen.queryByText("늦은 RAG 결과")).not.toBeInTheDocument());
    expect(paths.some((path) => path.includes("cursor=page-2"))).toBe(true);
    expect(paths.some((path) => path.includes("topic_key=fine-tuning") && !path.includes("cursor="))).toBe(true);
  });
});

function topics() {
  return [{ key: "rag", label: "RAG" }, { key: "fine-tuning", label: "파인튜닝" }];
}

function draft(overrides: Record<string, unknown> = {}) {
  return { title: "메모", body: "본문", kind: "note" as const, topic_keys: [], domain_labels: [], experiment: null, references: [], ...overrides };
}

function record(overrides: Record<string, unknown> = {}) {
  return { id: "11111111-1111-4111-8111-111111111111", revision: 1, created_at: "2026-09-07T01:02:03Z", updated_at: "2026-09-07T01:02:03Z", archived_at: null, draft: draft(), reference_views: [], dataset_reference_view: null, unavailable_reference_count: 0, ...overrides };
}

function summary(title: string) {
  return { id: crypto.randomUUID(), revision: 1, created_at: "2026-09-07T01:02:03Z", updated_at: "2026-09-07T01:02:03Z", archived_at: null, title, kind: "note", topic_keys: ["rag"] };
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
