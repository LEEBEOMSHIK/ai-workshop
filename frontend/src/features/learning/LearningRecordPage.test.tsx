import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { LearningRecordPage } from "./LearningRecordPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("LearningRecordPage", () => {
  it("preserves edited fields after 409 and rebases explicitly without automatic PUT", async () => {
    const puts: Array<Record<string, unknown>> = [];
    let detailReads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/learning/records/record-1" && !init?.method) {
        detailReads += 1;
        return jsonResponse(experimentRecord(detailReads === 1 ? 2 : 4, detailReads === 1 ? "서버 제목" : "최신 서버 제목"));
      }
      if (path === "/api/v1/learning/records/record-1" && init?.method === "PUT") {
        const payload = JSON.parse(String(init.body));
        puts.push(payload);
        if (puts.length === 1) return errorResponse(409, "learning_revision_conflict");
        return jsonResponse({ ...experimentRecord(5, payload.draft.title), draft: payload.draft });
      }
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    const editor = await screen.findByRole("region", { name: "기록 편집" });
    const title = within(editor).getByRole("textbox", { name: "제목" });
    await user.clear(title);
    await user.type(title, "내 충돌 초안");
    await user.clear(within(editor).getByRole("textbox", { name: "목적" }));
    await user.type(within(editor).getByRole("textbox", { name: "목적" }), "보존할 목적");
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("다른 revision");
    expect(within(editor).getByRole("textbox", { name: "제목" })).toHaveValue("내 충돌 초안");
    expect(within(editor).getByRole("textbox", { name: "목적" })).toHaveValue("보존할 목적");
    expect(puts).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "최신 버전 읽기" }));
    const latestSnapshot = await screen.findByRole("region", { name: "서버 최신 전체 내용" });
    expect(within(latestSnapshot).getByRole("textbox", { name: "제목" })).toHaveValue("최신 서버 제목");
    expect(within(latestSnapshot).getByRole("combobox", { name: "기록 종류" })).toHaveValue("experiment");
    expect(within(latestSnapshot).getByRole("textbox", { name: "목적" })).toHaveValue("서버 목적");
    expect(within(latestSnapshot).getByRole("textbox", { name: "도메인 분류" })).toHaveValue("research");
    expect(within(latestSnapshot).getByRole("link", { name: "RAG search" })).toHaveAttribute("href", "/workshop/rag/search");
    expect(within(editor).getByRole("textbox", { name: "제목" })).toHaveValue("내 충돌 초안");
    expect(puts).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "revision 4로 재기준화" }));
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));

    await waitFor(() => expect(puts).toHaveLength(2));
    expect(puts[1]).toMatchObject({ expected_revision: 4, draft: { title: "내 충돌 초안", experiment: { purpose: "보존할 목적" } } });
  }, 15_000);

  it("remounts the complete latest snapshot when a repeated conflict read returns a newer revision", async () => {
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/learning/records/record-1" && !init?.method) {
        reads += 1;
        if (reads === 1) return jsonResponse({ ...noteRecord(), revision: 2 });
        if (reads === 2) return jsonResponse({ ...noteRecord(), revision: 3, draft: { ...noteRecord().draft, title: "최신 메모", body: "최신 메모 본문" } });
        return jsonResponse({ ...experimentRecord(4, "더 최신 실험"), draft: { ...experimentRecord(4, "더 최신 실험").draft, body: "더 최신 실험 본문", experiment: { ...experimentRecord(4, "더 최신 실험").draft.experiment, purpose: "더 최신 목적" } } });
      }
      if (path === "/api/v1/learning/records/record-1" && init?.method === "PUT") return errorResponse(409, "learning_revision_conflict");
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    const editor = await screen.findByRole("region", { name: "기록 편집" });
    await user.type(within(editor).getByRole("textbox", { name: "제목" }), " 수정");
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));
    await user.click(await screen.findByRole("button", { name: "최신 버전 읽기" }));
    let latest = await screen.findByRole("region", { name: "서버 최신 전체 내용" });
    expect(within(latest).getByRole("textbox", { name: "제목" })).toHaveValue("최신 메모");
    expect(within(latest).getByRole("combobox", { name: "기록 종류" })).toHaveValue("note");
    await user.click(screen.getByRole("button", { name: "최신 버전 읽기" }));
    await screen.findByRole("heading", { name: "서버의 최신 revision 4" });

    latest = screen.getByRole("region", { name: "서버 최신 전체 내용" });
    expect(within(latest).getByRole("textbox", { name: "제목" })).toHaveValue("더 최신 실험");
    expect(within(latest).getByRole("combobox", { name: "기록 종류" })).toHaveValue("experiment");
    expect(within(latest).getByRole("textbox", { name: "본문" })).toHaveValue("더 최신 실험 본문");
    expect(within(latest).getByRole("textbox", { name: "목적" })).toHaveValue("더 최신 목적");
  }, 15_000);

  it("applies an archived latest record after a save conflict, restores it, and keeps the local draft for manual save", async () => {
    const puts: Array<Record<string, unknown>> = [];
    const restores: number[] = [];
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/learning/records/record-1" && !init?.method) {
        reads += 1;
        return jsonResponse(reads === 1
          ? experimentRecord(2, "초기 실험")
          : { ...experimentRecord(3, "서버 보관 실험"), archived_at: "2026-09-07T02:00:00Z" });
      }
      if (path === "/api/v1/learning/records/record-1" && init?.method === "PUT") {
        const payload = JSON.parse(String(init.body));
        puts.push(payload);
        if (puts.length === 1) return errorResponse(409, "learning_revision_conflict");
        return jsonResponse({ ...experimentRecord(5, payload.draft.title), draft: payload.draft });
      }
      if (path.endsWith("/restore") && init?.method === "POST") {
        restores.push(JSON.parse(String(init.body)).expected_revision);
        return jsonResponse(experimentRecord(4, "서버 보관 실험"));
      }
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    const editor = await screen.findByRole("region", { name: "기록 편집" });
    await user.clear(within(editor).getByRole("textbox", { name: "제목" }));
    await user.type(within(editor).getByRole("textbox", { name: "제목" }), "보존할 로컬 제목");
    await user.clear(within(editor).getByRole("textbox", { name: "본문" }));
    await user.type(within(editor).getByRole("textbox", { name: "본문" }), "보존할 로컬 본문");
    await user.clear(within(editor).getByRole("textbox", { name: "목적" }));
    await user.type(within(editor).getByRole("textbox", { name: "목적" }), "보존할 로컬 목적");
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));
    await user.click(await screen.findByRole("button", { name: "최신 버전 읽기" }));
    await screen.findByRole("region", { name: "서버 최신 전체 내용" });
    await user.click(screen.getByRole("button", { name: "revision 3로 재기준화" }));

    expect(screen.getByRole("button", { name: "기록 복원" })).toBeVisible();
    expect(within(editor).getByRole("textbox", { name: "제목" })).toBeDisabled();
    expect(within(editor).getByRole("textbox", { name: "제목" })).toHaveValue("보존할 로컬 제목");
    await user.click(screen.getByRole("button", { name: "기록 복원" }));
    await waitFor(() => expect(within(editor).getByRole("textbox", { name: "제목" })).toBeEnabled());
    expect(within(editor).getByRole("textbox", { name: "본문" })).toHaveValue("보존할 로컬 본문");
    expect(within(editor).getByRole("textbox", { name: "목적" })).toHaveValue("보존할 로컬 목적");
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));

    await waitFor(() => expect(puts).toHaveLength(2));
    expect(restores).toEqual([3]);
    expect(puts[1]).toMatchObject({ expected_revision: 4, draft: { title: "보존할 로컬 제목", body: "보존할 로컬 본문", experiment: { purpose: "보존할 로컬 목적" } } });
  }, 15_000);

  it("requires confirmation before converting a note and retains its body and references", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const puts: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/learning/records/record-1" && init?.method === "PUT") {
        const payload = JSON.parse(String(init.body));
        puts.push(payload);
        return jsonResponse({ ...noteRecord(), revision: 2, draft: payload.draft });
      }
      if (path === "/api/v1/learning/records/record-1") return jsonResponse(noteRecord());
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    const kind = await screen.findByRole("combobox", { name: "기록 종류" });
    await user.selectOptions(kind, "experiment");
    expect(kind).toHaveValue("note");
    expect(puts).toHaveLength(0);
    await user.selectOptions(kind, "experiment");
    expect(kind).toHaveValue("experiment");
    await user.click(screen.getByRole("button", { name: "변경 저장" }));

    expect(confirm).toHaveBeenCalledTimes(2);
    expect(puts).toHaveLength(1);
    expect(puts[0]).toMatchObject({ expected_revision: 1, draft: { kind: "experiment", body: "원문 본문", references: [{ kind: "service", target: "rag.search", version: null }] } });
  });

  it("loads historical revisions read-only and archives then restores only after successful responses", async () => {
    const actions: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/revisions/1")) return jsonResponse({ ...noteRecord(), draft: { ...noteRecord().draft, body: "과거 본문" } });
      if (path.endsWith("/archive")) { actions.push("archive"); return jsonResponse({ ...noteRecord(), revision: 3, archived_at: "2026-09-07T02:00:00Z" }); }
      if (path.endsWith("/restore")) { actions.push("restore"); return jsonResponse({ ...noteRecord(), revision: 4, archived_at: null }); }
      if (path === "/api/v1/learning/records/record-1") return jsonResponse({ ...noteRecord(), revision: 2 });
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    await user.selectOptions(await screen.findByRole("combobox", { name: "revision 보기" }), "1");
    expect(await screen.findByRole("textbox", { name: "본문" })).toHaveValue("과거 본문");
    expect(screen.queryByRole("button", { name: "변경 저장" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "현재 revision으로 돌아가기" }));
    await user.click(screen.getByRole("button", { name: "기록 보관" }));
    expect(await screen.findByText("보관된 기록입니다. 복원한 뒤 편집할 수 있습니다.")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "제목" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "기록 복원" }));
    await waitFor(() => expect(actions).toEqual(["archive", "restore"]));
    expect(screen.getByRole("textbox", { name: "제목" })).toBeEnabled();
  });

  it("keeps a dirty editing session and its navigation guard mounted while viewing history", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/revisions/1")) return jsonResponse({ ...noteRecord(), draft: { ...noteRecord().draft, title: "과거 메모", body: "과거 본문" } });
      if (path === "/api/v1/learning/records/record-1") return jsonResponse(experimentRecord(2, "현재 실험"));
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    let editor = await screen.findByRole("region", { name: "기록 편집" });
    await user.clear(within(editor).getByRole("textbox", { name: "제목" }));
    await user.type(within(editor).getByRole("textbox", { name: "제목" }), "보존할 제목");
    await user.clear(within(editor).getByRole("textbox", { name: "본문" }));
    await user.type(within(editor).getByRole("textbox", { name: "본문" }), "보존할 본문");
    await user.clear(within(editor).getByRole("textbox", { name: "목적" }));
    await user.type(within(editor).getByRole("textbox", { name: "목적" }), "보존할 목적");
    await user.selectOptions(screen.getByRole("combobox", { name: "revision 보기" }), "1");
    expect(await screen.findByRole("textbox", { name: "본문" })).toHaveValue("과거 본문");
    expect(screen.getByRole("link", { name: "학습 기록 목록" }).dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))).toBe(false);
    expect(confirm).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: "현재 revision으로 돌아가기" }));

    editor = screen.getByRole("region", { name: "기록 편집" });
    expect(within(editor).getByRole("textbox", { name: "제목" })).toHaveValue("보존할 제목");
    expect(within(editor).getByRole("textbox", { name: "본문" })).toHaveValue("보존할 본문");
    expect(within(editor).getByRole("textbox", { name: "목적" })).toHaveValue("보존할 목적");
    expect(within(editor).getByRole("region", { name: "본문 미리보기" })).toHaveTextContent("보존할 본문");
  });

  it("remounts the complete readonly history snapshot when the selected revision changes", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/revisions/1")) return jsonResponse({ ...noteRecord(), revision: 1, draft: { ...noteRecord().draft, title: "revision 1 메모", body: "revision 1 본문" } });
      if (path.endsWith("/revisions/2")) return jsonResponse({ ...experimentRecord(2, "revision 2 실험"), draft: { ...experimentRecord(2, "revision 2 실험").draft, body: "revision 2 본문", experiment: { ...experimentRecord(2, "revision 2 실험").draft.experiment, purpose: "revision 2 목적" } } });
      if (path === "/api/v1/learning/records/record-1") return jsonResponse(experimentRecord(3, "현재 실험"));
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    const revisions = await screen.findByRole("combobox", { name: "revision 보기" });
    await user.selectOptions(revisions, "1");
    expect(await screen.findByRole("textbox", { name: "제목" })).toHaveValue("revision 1 메모");
    expect(screen.getByRole("combobox", { name: "기록 종류" })).toHaveValue("note");
    await user.selectOptions(revisions, "2");

    expect(await screen.findByRole("textbox", { name: "제목" })).toHaveValue("revision 2 실험");
    expect(screen.getByRole("combobox", { name: "기록 종류" })).toHaveValue("experiment");
    expect(screen.getByRole("textbox", { name: "목적" })).toHaveValue("revision 2 목적");
    expect(screen.getByRole("textbox", { name: "본문" })).toHaveValue("revision 2 본문");
  });

  it("invalidates a pending historical response when current revision is selected", async () => {
    const history = deferred<Response>();
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/revisions/1")) return history.promise;
      if (path === "/api/v1/learning/records/record-1") return jsonResponse({ ...noteRecord(), revision: 2 });
      return optionResponse(path);
    }));
    render(<LearningRecordPage recordId="record-1" />);

    const revisions = await screen.findByRole("combobox", { name: "revision 보기" });
    fireEvent.change(revisions, { target: { value: "1" } });
    fireEvent.change(revisions, { target: { value: "2" } });
    await act(async () => history.resolve(jsonResponse({ ...noteRecord(), draft: { ...noteRecord().draft, body: "늦은 과거 본문" } })));

    await waitFor(() => expect(screen.queryByDisplayValue("늦은 과거 본문")).not.toBeInTheDocument());
    expect(within(screen.getByRole("region", { name: "기록 편집" })).getByRole("textbox", { name: "본문" })).toHaveValue("원문 본문");
  });

  it("keeps a dirty editor and skips archive when discard is cancelled", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const archives: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/archive")) { archives.push(init ?? {}); return jsonResponse({ ...noteRecord(), revision: 2, archived_at: "2026-09-07T02:00:00Z" }); }
      if (path === "/api/v1/learning/records/record-1") return jsonResponse(noteRecord());
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    const editor = await screen.findByRole("region", { name: "기록 편집" });
    await user.clear(within(editor).getByRole("textbox", { name: "본문" }));
    await user.type(within(editor).getByRole("textbox", { name: "본문" }), "실시간 초안 본문");
    expect(within(editor).getByRole("region", { name: "본문 미리보기" })).toHaveTextContent("실시간 초안 본문");
    await user.click(screen.getByRole("button", { name: "기록 보관" }));

    expect(confirm).toHaveBeenCalled();
    expect(archives).toHaveLength(0);
    expect(within(editor).getByRole("textbox", { name: "본문" })).toHaveValue("실시간 초안 본문");
  });

  it("serializes save and archive through one pending action guard", async () => {
    const save = deferred<Response>();
    let archives = 0;
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const historyGo = vi.spyOn(window.history, "go").mockImplementation(() => undefined);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/learning/records/record-1" && init?.method === "PUT") return save.promise;
      if (path.endsWith("/archive")) { archives += 1; return jsonResponse({ ...noteRecord(), revision: 3, archived_at: "2026-09-07T02:00:00Z" }); }
      if (path === "/api/v1/learning/records/record-1") return jsonResponse(noteRecord());
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    const editor = await screen.findByRole("region", { name: "기록 편집" });
    await user.type(within(editor).getByRole("textbox", { name: "제목" }), " 수정");
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));

    expect(screen.getByRole("button", { name: "처리 중…" })).toBeDisabled();
    expect(archives).toBe(0);
    const reload = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(reload);
    expect(reload.defaultPrevented).toBe(true);
    expect(screen.getByRole("link", { name: "학습 기록 목록" }).dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))).toBe(false);
    window.dispatchEvent(new PopStateEvent("popstate"));
    expect(historyGo).toHaveBeenCalledWith(1);
    await act(async () => save.resolve(jsonResponse({ ...noteRecord(), revision: 2, draft: { ...noteRecord().draft, title: "기존 메모 수정" } })));
    await waitFor(() => expect(screen.getByRole("button", { name: "기록 보관" })).toBeEnabled());
    expect(archives).toBe(0);
    const afterSave = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(afterSave);
    expect(afterSave.defaultPrevented).toBe(false);
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it("applies latest archive state after 409, preserves the draft, and retries from the latest revision", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const actions: Array<{ action: string; revision: number }> = [];
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/learning/records/record-1" && !init?.method) {
        reads += 1;
        return jsonResponse(reads === 1
          ? { ...experimentRecord(2, "초기 제목"), archived_at: null }
          : { ...experimentRecord(4, "다른 사용자의 최신 제목"), archived_at: "2026-09-07T02:00:00Z" });
      }
      if (path.endsWith("/archive") && init?.method === "POST") {
        actions.push({ action: "archive", revision: JSON.parse(String(init.body)).expected_revision });
        return errorResponse(409, "learning_revision_conflict");
      }
      if (path.endsWith("/restore") && init?.method === "POST") {
        actions.push({ action: "restore", revision: JSON.parse(String(init.body)).expected_revision });
        return jsonResponse({ ...experimentRecord(5, "다른 사용자의 최신 제목"), archived_at: null });
      }
      if (path === "/api/v1/learning/records/record-1" && init?.method === "PUT") {
        const payload = JSON.parse(String(init.body));
        actions.push({ action: "save", revision: payload.expected_revision });
        return jsonResponse({ ...experimentRecord(6, payload.draft.title), draft: payload.draft, archived_at: null });
      }
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    const editor = await screen.findByRole("region", { name: "기록 편집" });
    await user.clear(within(editor).getByRole("textbox", { name: "제목" }));
    await user.type(within(editor).getByRole("textbox", { name: "제목" }), "보존할 로컬 초안");
    await user.click(screen.getByRole("button", { name: "기록 보관" }));
    await user.click(await screen.findByRole("button", { name: "최신 버전 읽기" }));
    await screen.findByRole("region", { name: "서버 최신 전체 내용" });
    await user.click(screen.getByRole("button", { name: "최신 상태 적용" }));

    expect(screen.getByRole("button", { name: "기록 복원" })).toBeVisible();
    expect(within(editor).getByRole("textbox", { name: "제목" })).toBeDisabled();
    expect(within(editor).getByRole("textbox", { name: "제목" })).toHaveValue("보존할 로컬 초안");
    await user.click(screen.getByRole("button", { name: "기록 복원" }));
    await waitFor(() => expect(within(editor).getByRole("textbox", { name: "제목" })).toBeEnabled());
    expect(within(editor).getByRole("textbox", { name: "제목" })).toHaveValue("보존할 로컬 초안");
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));

    await waitFor(() => expect(actions).toEqual([
      { action: "archive", revision: 2 },
      { action: "restore", revision: 4 },
      { action: "save", revision: 5 },
    ]));
  }, 15_000);

  it("syncs a clean editor to the latest full draft after an archive conflict before restore and save", async () => {
    const puts: Array<Record<string, unknown>> = [];
    let reads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/learning/records/record-1" && !init?.method) {
        reads += 1;
        return jsonResponse(reads === 1
          ? { ...noteRecord(), revision: 2 }
          : { ...experimentRecord(4, "최신 실험"), archived_at: "2026-09-07T02:00:00Z", draft: { ...experimentRecord(4, "최신 실험").draft, body: "최신 서버 본문" } });
      }
      if (path.endsWith("/archive") && init?.method === "POST") return errorResponse(409, "learning_revision_conflict");
      if (path.endsWith("/restore") && init?.method === "POST") return jsonResponse({ ...experimentRecord(5, "최신 실험"), archived_at: null, draft: { ...experimentRecord(5, "최신 실험").draft, body: "최신 서버 본문" } });
      if (path === "/api/v1/learning/records/record-1" && init?.method === "PUT") {
        const payload = JSON.parse(String(init.body));
        puts.push(payload);
        return jsonResponse({ ...experimentRecord(6, payload.draft.title), draft: payload.draft });
      }
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    await user.click(await screen.findByRole("button", { name: "기록 보관" }));
    await user.click(await screen.findByRole("button", { name: "최신 버전 읽기" }));
    await screen.findByRole("region", { name: "서버 최신 전체 내용" });
    await user.click(screen.getByRole("button", { name: "최신 상태 적용" }));

    let editor = screen.getByRole("region", { name: "기록 편집" });
    expect(within(editor).getByRole("combobox", { name: "기록 종류" })).toHaveValue("experiment");
    expect(within(editor).getByRole("textbox", { name: "본문" })).toHaveValue("최신 서버 본문");
    expect(within(editor).getByRole("textbox", { name: "목적" })).toHaveValue("서버 목적");
    await user.click(screen.getByRole("button", { name: "기록 복원" }));
    editor = await screen.findByRole("region", { name: "기록 편집" });
    await user.type(within(editor).getByRole("textbox", { name: "제목" }), " 수정");
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toMatchObject({ expected_revision: 5, draft: { title: "최신 실험 수정", body: "최신 서버 본문", kind: "experiment", experiment: { purpose: "서버 목적" } } });
  }, 15_000);

  it("renders unavailable references without leaked labels and keeps hostile body inert", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/learning/records/record-1") return jsonResponse({
        ...noteRecord(),
        draft: { ...noteRecord().draft, body: '<script>alert(1)</script> ![x](https://invalid.test/x)' },
        reference_views: [{ status: "unavailable", label: null, href: null, key: null }],
        unavailable_reference_count: 1,
      });
      return optionResponse(path);
    }));
    const { container } = render(<LearningRecordPage recordId="record-1" />);

    expect(await screen.findByText("접근할 수 없는 참조 1개")).toBeVisible();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("a[href='https://invalid.test/x']")).toBeNull();
  });

  it("requires explicit confirmation before a sanitized draft removes unavailable references", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    const puts: RequestInit[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/learning/records/record-1" && init?.method === "PUT") {
        puts.push(init);
        const payload = JSON.parse(String(init.body));
        return jsonResponse({ ...noteRecord(), revision: 2, draft: payload.draft, unavailable_reference_count: 0 });
      }
      if (path === "/api/v1/learning/records/record-1") return jsonResponse({
        ...noteRecord(),
        draft: { ...noteRecord().draft, references: [] },
        reference_views: [{ status: "unavailable", label: null, href: null, key: null }],
        unavailable_reference_count: 1,
      });
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    await user.clear(await screen.findByRole("textbox", { name: "제목" }));
    await user.type(screen.getByRole("textbox", { name: "제목" }), "정리된 초안");
    await user.click(screen.getByRole("button", { name: "변경 저장" }));
    expect(puts).toHaveLength(0);
    expect(screen.getByRole("textbox", { name: "제목" })).toHaveValue("정리된 초안");
    await user.click(screen.getByRole("button", { name: "변경 저장" }));

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(JSON.parse(String(puts[0]?.body))).toMatchObject({ draft: { references: [] } });
  });

  it("does not let an older record load overwrite a newer route", async () => {
    const first = deferred<Response>();
    const second = deferred<Response>();
    const fetch = vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/learning/records/record-a") return first.promise;
      if (path === "/api/v1/learning/records/record-b") return second.promise;
      return optionResponse(path);
    });
    vi.stubGlobal("fetch", fetch);
    const view = render(<LearningRecordPage recordId="record-a" />);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith(
      "/api/v1/learning/records/record-a",
      expect.objectContaining({ credentials: "include" }),
    ));
    view.rerender(<LearningRecordPage recordId="record-b" />);

    await act(async () => second.resolve(jsonResponse({ ...noteRecord(), id: "record-b", draft: { ...noteRecord().draft, title: "새 경로 기록" } })));
    expect(await screen.findByRole("heading", { name: "새 경로 기록", level: 1 })).toBeVisible();
    await act(async () => first.resolve(jsonResponse({ ...noteRecord(), id: "record-a", draft: { ...noteRecord().draft, title: "늦은 이전 기록" } })));

    await waitFor(() => expect(screen.queryByText("늦은 이전 기록")).not.toBeInTheDocument());
  });

  it("clears conflict state and ignores late latest responses after the record route changes", async () => {
    const oldLatest = deferred<Response>();
    let oldReads = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path === "/api/v1/learning/records/record-a" && init?.method === "PUT") return errorResponse(409, "learning_revision_conflict");
      if (path === "/api/v1/learning/records/record-a") {
        oldReads += 1;
        return oldReads === 1 ? jsonResponse({ ...noteRecord(), id: "record-a" }) : oldLatest.promise;
      }
      if (path === "/api/v1/learning/records/record-b") return jsonResponse({ ...noteRecord(), id: "record-b", draft: { ...noteRecord().draft, title: "새 기록" } });
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    const view = render(<LearningRecordPage recordId="record-a" />);

    const editor = await screen.findByRole("region", { name: "기록 편집" });
    await user.type(within(editor).getByRole("textbox", { name: "제목" }), " 수정");
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));
    await user.click(await screen.findByRole("button", { name: "최신 버전 읽기" }));
    view.rerender(<LearningRecordPage recordId="record-b" />);
    expect(await screen.findByRole("heading", { name: "새 기록", level: 1 })).toBeVisible();
    await act(async () => oldLatest.resolve(jsonResponse({ ...noteRecord(), id: "record-a", revision: 8, draft: { ...noteRecord().draft, title: "늦은 최신 기록" } })));

    await waitFor(() => expect(screen.queryByText("늦은 최신 기록")).not.toBeInTheDocument());
    expect(screen.queryByRole("heading", { name: "revision 충돌" })).not.toBeInTheDocument();
  });

  it.each([
    { action: "archive", archivedAt: null, button: "기록 보관", still: "기록 보관" },
    { action: "restore", archivedAt: "2026-09-07T02:00:00Z", button: "기록 복원", still: "기록 복원" },
  ])("keeps the screen unchanged when $action has a revision conflict", async ({ action, archivedAt, button, still }) => {
    let mutations = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith(`/${action}`) && init?.method === "POST") {
        mutations += 1;
        return errorResponse(409, "learning_revision_conflict");
      }
      if (path === "/api/v1/learning/records/record-1") return jsonResponse({ ...noteRecord(), archived_at: archivedAt });
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    await user.click(await screen.findByRole("button", { name: button }));

    expect(await screen.findByRole("alert")).toHaveTextContent("보관 상태");
    expect(screen.getByRole("button", { name: still })).toBeVisible();
    expect(mutations).toBe(1);
  });
});

function noteRecord() {
  return { id: "record-1", revision: 1, created_at: "2026-09-07T01:02:03Z", updated_at: "2026-09-07T01:02:03Z", archived_at: null, draft: { title: "기존 메모", body: "원문 본문", kind: "note", topic_keys: ["rag"], domain_labels: ["research"], experiment: null, references: [{ kind: "service", target: "rag.search", version: null }] }, reference_views: [{ status: "available", label: "RAG search", href: "/workshop/rag/search", key: { kind: "service", target: "rag.search", version: null } }], dataset_reference_view: null, unavailable_reference_count: 0 };
}

function experimentRecord(revision: number, title: string) {
  return { ...noteRecord(), revision, draft: { ...noteRecord().draft, title, kind: "experiment", experiment: { status: "planned", purpose: "서버 목적", hypothesis: null, configurations: [], environment: null, procedure: null, observations: null, metrics: [], limitations: null, conclusion: null, next_steps: [], troubleshooting: null, dataset_snapshot: null } } };
}

function optionResponse(path: string): Response {
  if (path === "/api/v1/learning/topics") return jsonResponse([{ key: "rag", label: "RAG" }]);
  if (path.startsWith("/api/v1/learning/records?" ) || path === "/api/v1/learning/records") return jsonResponse({ items: [{ id: "other-record", revision: 1, created_at: "2026-09-07T00:00:00Z", updated_at: "2026-09-07T00:00:00Z", archived_at: null, title: "다른 학습 기록", kind: "note", topic_keys: ["rag"] }], next_cursor: null });
  if (path === "/api/v1/rag/evaluation-runs?limit=20") return jsonResponse([]);
  throw new Error(`Unexpected request: ${path}`);
}

function jsonResponse(value: unknown, status = 200): Response {
  return new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
}

function errorResponse(status: number, code: string): Response {
  return jsonResponse({ error: { code, message: "safe", correlation_id: "corr" } }, status);
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => { resolve = done; });
  return { promise, resolve };
}
