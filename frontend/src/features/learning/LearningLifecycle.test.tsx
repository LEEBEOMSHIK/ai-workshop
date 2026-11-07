import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import type { LearningDraft, LearningRecord } from "./api";
import { LearningListPage } from "./LearningListPage";
import { LearningRecordPage } from "./LearningRecordPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("private Learning component/API lifecycle", () => {
  it("creates, refetches, explicitly rebases, converts, archives, and restores", async () => {
    const recordId = "11111111-1111-4111-8111-111111111111";
    const requests: Array<{ method: string; path: string; body: unknown }> = [];
    let current: LearningRecord | null = null;
    let conflictPending = true;

    const confirm = vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      const method = init?.method ?? "GET";
      const body = typeof init?.body === "string" ? JSON.parse(init.body) : null;
      requests.push({ method, path, body });

      if (path === "/api/v1/learning/topics") {
        return jsonResponse([{ key: "rag", label: "RAG" }]);
      }
      if (path === "/api/v1/rag/evaluation-runs?limit=20") {
        return jsonResponse([]);
      }
      if (path.startsWith("/api/v1/learning/records?") && method === "GET") {
        return jsonResponse({
          items: current ? [summary(current)] : [],
          next_cursor: null,
        });
      }
      if (path === "/api/v1/learning/records" && method === "POST") {
        current = record(recordId, 1, body as LearningDraft, null);

        return jsonResponse(current, 201);
      }
      if (path === `/api/v1/learning/records/${recordId}` && method === "GET") {
        if (!current) throw new Error("record must be created before detail reads");
        return jsonResponse(current);
      }
      if (path === `/api/v1/learning/records/${recordId}` && method === "PUT") {
        const payload = body as { expected_revision: number; draft: LearningDraft };
        if (conflictPending) {
          conflictPending = false;
          if (!current) throw new Error("current record is missing");
          current = record(
            recordId,
            2,
            { ...current.draft, title: "서버의 revision 2 메모" },
            null,
          );

          return errorResponse(409, "learning_revision_conflict");
        }
        if (!current || payload.expected_revision !== current.revision) {
          return errorResponse(409, "learning_revision_conflict");
        }
        current = record(recordId, current.revision + 1, payload.draft, null);

        return jsonResponse(current);
      }
      if (path === `/api/v1/learning/records/${recordId}/archive` && method === "POST") {
        const payload = body as { expected_revision: number };
        if (!current || payload.expected_revision !== current.revision) {
          return errorResponse(409, "learning_revision_conflict");
        }
        current = record(
          recordId,
          current.revision + 1,
          current.draft,
          "2026-09-07T04:00:00Z",
        );

        return jsonResponse(current);
      }
      if (path === `/api/v1/learning/records/${recordId}/restore` && method === "POST") {
        const payload = body as { expected_revision: number };
        if (!current || payload.expected_revision !== current.revision) {
          return errorResponse(409, "learning_revision_conflict");
        }
        current = record(recordId, current.revision + 1, current.draft, null);

        return jsonResponse(current);
      }
      throw new Error(`Unexpected request: ${method} ${path}`);
    }));

    const onCreated = vi.fn();
    const user = userEvent.setup();
    const listView = render(<LearningListPage onCreated={onCreated} />);

    await user.click(screen.getByRole("button", { name: "새 기록" }));
    await user.type(screen.getByRole("textbox", { name: "제목" }), "통합 메모");
    await user.type(screen.getByRole("textbox", { name: "본문" }), "보존할 원문");
    await user.click(screen.getByRole("button", { name: "기록 저장" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(onCreated).toHaveBeenCalledWith(expect.objectContaining({ id: recordId, revision: 1 }));
    listView.unmount();

    render(<LearningRecordPage recordId={recordId} />);
    expect(await screen.findByRole("heading", { name: "통합 메모", level: 1 })).toBeVisible();
    expect(screen.queryByRole("combobox", { name: "버전 보기" })).not.toBeInTheDocument();
    expect(screen.queryByText(/버전 1/)).not.toBeInTheDocument();
    expect(screen.getByText("보존할 원문")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "본문" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "기록 편집" }));
    let editor = screen.getByRole("region", { name: "기록 편집" });
    expect(within(editor).getByRole("textbox", { name: "본문" })).toHaveValue("보존할 원문");

    await user.click(within(editor).getByRole("checkbox", { name: "실험 항목 추가" }));
    expect(confirm).not.toHaveBeenCalled();
    await user.type(within(editor).getByRole("textbox", { name: "목적" }), "전환 확인");
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));

    expect(await screen.findByRole("heading", { name: "다른 변경 사항이 있습니다" })).toBeVisible();
    editor = screen.getByRole("region", { name: "기록 편집" });
    expect(within(editor).getByRole("checkbox", { name: "실험 항목 추가" })).toBeChecked();
    expect(within(editor).getByRole("textbox", { name: "목적" })).toHaveValue("전환 확인");
    expect(mutationRequests(requests, "PUT")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: "저장된 내용 확인" }));
    expect(await screen.findByRole("heading", { name: "현재 저장된 내용" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "현재 내용을 기준으로 편집 계속" }));
    expect(mutationRequests(requests, "PUT")).toHaveLength(1);
    editor = screen.getByRole("region", { name: "기록 편집" });
    expect(within(editor).getByRole("textbox", { name: "목적" })).toHaveValue("전환 확인");

    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));
    await screen.findByRole("region", { name: "기록 읽기" });
    expect(within(screen.getByRole("region", { name: "기록 읽기" })).getByText("전환 확인")).toBeVisible();
    expect(mutationRequests(requests, "PUT")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: "기록 보관" }));
    expect(await screen.findByRole("button", { name: "기록 복원" })).toBeVisible();
    expect(screen.getByText("보관된 기록입니다. 복원한 뒤 편집할 수 있습니다.")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "기록 복원" }));
    expect(await screen.findByRole("button", { name: "기록 보관" })).toBeVisible();
    expect(screen.getByText("전환 확인")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "기록 편집" }));
    editor = screen.getByRole("region", { name: "기록 편집" });
    expect(within(editor).getByRole("textbox", { name: "목적" })).toHaveValue("전환 확인");
    expect(within(editor).getByRole("textbox", { name: "목적" })).toBeEnabled();

    const mutations = requests.filter(({ method }) => method !== "GET");
    expect(mutations.map(({ method, path }) => [method, path])).toEqual([
      ["POST", "/api/v1/learning/records"],
      ["PUT", `/api/v1/learning/records/${recordId}`],
      ["PUT", `/api/v1/learning/records/${recordId}`],
      ["POST", `/api/v1/learning/records/${recordId}/archive`],
      ["POST", `/api/v1/learning/records/${recordId}/restore`],
    ]);
    expect((mutations[0]?.body as LearningDraft)).toMatchObject({
      title: "통합 메모",
      body: "보존할 원문",
      kind: "note",
      experiment: null,
    });
    expect(mutations[1]?.body).toMatchObject({
      expected_revision: 1,
      draft: {
        title: "통합 메모",
        body: "보존할 원문",
        kind: "experiment",
        experiment: { purpose: "전환 확인" },
      },
    });
    expect(mutations[2]?.body).toEqual({
      ...(mutations[1]?.body as { expected_revision: number; draft: LearningDraft }),
      expected_revision: 2,
    });
    expect(mutations[3]?.body).toEqual({ expected_revision: 3 });
    expect(mutations[4]?.body).toEqual({ expected_revision: 4 });
    expect(current).toMatchObject({ revision: 5, archived_at: null });
    expect(current).toMatchObject({ draft: {
      kind: "experiment",
      body: "보존할 원문",
      experiment: { purpose: "전환 확인" },
    } });
  }, 20_000);
});

function record(
  id: string,
  revision: number,
  draft: LearningDraft,
  archivedAt: string | null,
): LearningRecord {
  return {
    id,
    revision,
    created_at: "2026-09-07T01:00:00Z",
    updated_at: `2026-09-07T0${Math.min(revision, 9)}:00:00Z`,
    archived_at: archivedAt,
    draft,
    reference_views: [],
    dataset_reference_view: null,
    unavailable_reference_count: 0,
  };
}

function summary(value: LearningRecord) {
  return {
    id: value.id,
    revision: value.revision,
    created_at: value.created_at,
    updated_at: value.updated_at,
    archived_at: value.archived_at,
    title: value.draft.title,
    kind: value.draft.kind,
    topic_keys: value.draft.topic_keys,
  };
}

function mutationRequests(
  requests: Array<{ method: string; path: string; body: unknown }>,
  method: string,
) {
  return requests.filter((request) => request.method === method);
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function errorResponse(status: number, code: string): Response {
  return jsonResponse({ error: { code, message: "safe", correlation_id: "corr" } }, status);
}
