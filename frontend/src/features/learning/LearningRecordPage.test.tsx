import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { LearningRecordPage } from "./LearningRecordPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("LearningRecordPage", () => {
  it("presents the purpose, question, target and actual answers together for a measured comparison", async () => {
    const result = experimentRecord(2, "규정 인용하기");
    const observations = [
      "같은 질문의 실제 답변 비교",
      "질문  근거가 무엇인가요?",
      "학습 정답  정답에 포함된 인용 [e1]",
      "학습 전(원본)  학습하기 전의 답변",
      "학습 후(어댑터 적용)  학습한 뒤의 답변 [e1]",
      "",
      "인용을 확인했다.",
      "평가 조건: 샘플링 없이 최대 48토큰으로 생성했다.",
    ].join("\n");
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) !== "/api/v1/learning/records/record-1") return optionResponse(String(input));
      return jsonResponse({ ...result, draft: { ...result.draft, experiment: {
        ...result.draft.experiment, observations, conclusion: "기록된 결론",
        environment: "실험용 CPU", procedure: "seed 11, 배치 2, SGD, 3스텝.",
      } } });
    }));
    render(<LearningRecordPage recordId="record-1" />);
    const purpose = await screen.findByText("서버 목적");
    const comparisonHeading = screen.getByRole("heading", { name: "학습 전후 답변 비교" });
    expect(purpose.compareDocumentPosition(comparisonHeading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(screen.getByText("근거가 무엇인가요?")).toBeVisible();
    expect(screen.getByRole("article", { name: "학습 정답" })).toHaveTextContent("정답에 포함된 인용 [e1]");
    expect(screen.getByRole("article", { name: "학습 전" })).toHaveTextContent("학습하기 전의 답변");
    expect(screen.getByRole("article", { name: "학습 후" })).toHaveTextContent("학습한 뒤의 답변 [e1]");
    expect(screen.getByText("기록된 결론")).toBeVisible();
    expect(screen.getByText("인용을 확인했다.")).toBeInTheDocument();
    const settings = screen.getByRole("list", { name: "기록된 설정값" });
    expect(settings).toHaveTextContent(/Seed\s*11/);
    expect(settings).toHaveTextContent(/배치 크기\s*2/);
    expect(settings).toHaveTextContent(/응답 토큰 상한\s*48/);
    expect(settings).not.toHaveTextContent("BF16");
    expect(screen.getByText("샘플링 없이 최대 48토큰으로 생성했다.")).toBeVisible();
    const environment = screen.getByText("실행 환경 자세히 보기");
    const user = userEvent.setup();
    await user.click(environment);
    expect(screen.getByText("실험용 CPU")).toBeVisible();
    await user.click(environment);
    expect(environment.closest("details")).not.toHaveAttribute("open");
  });

  it("shows classification by the current title without version controls and reserves bullets for multiple entries", async () => {
    const current = experimentRecord(2, "합성 기록");
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/learning/records/record-1") {
        return jsonResponse({ ...current, draft: { ...current.draft, experiment: {
          ...current.draft.experiment, configurations: ["동일 조건 비교"], next_steps: ["자료 검수", "재측정"],
        } } });
      }
      return optionResponse(path);
    }));
    render(<LearningRecordPage recordId="record-1" />);
    const header = (await screen.findByRole("heading", { level: 1 })).closest("header");
    expect(header).toHaveTextContent("구조화 실험");
    expect(header).toHaveTextContent("RAG");
    expect(header).toHaveTextContent("research");
    expect(screen.queryByRole("heading", { name: "분류" })).not.toBeInTheDocument();
    expect(screen.getByText("동일 조건 비교").closest("li")).toBeNull();
    const steps = screen.getByText("자료 검수").closest("ul");
    expect(steps).toBeInTheDocument();
    expect(within(steps!).getAllByRole("listitem").map(item => item.textContent)).toEqual(["자료 검수", "재측정"]);

    expect(header).not.toHaveTextContent("버전");
    expect(screen.queryByRole("combobox", { name: "버전 보기" })).not.toBeInTheDocument();
    expect(header).toHaveTextContent("실험 상태계획");
  });

  it("leads with the conclusion and places evaluation scope and limitations immediately after the method", async () => {
    const result = experimentRecord(2, "합성 비교 실험");
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) !== "/api/v1/learning/records/record-1") return optionResponse(String(input));
      return jsonResponse({...result, draft: {...result.draft, experiment: {
        ...result.draft.experiment, conclusion: "검색 결과가 개선됨", limitations: "공개 예시만 사용함",
        observations: "기존 관찰 메모를 그대로 표시한다.",
        metrics: [{ name: "정답률", value: 80, unit: "%" }],
      }}});
    }));
    render(<LearningRecordPage recordId="record-1" />);
    const conclusion = await screen.findByText("검색 결과가 개선됨");
    const body = screen.getByText("원문 본문");
    const method = screen.getByRole("heading", { name: "실험 방법" }).closest("section")!;
    const scope = screen.getByRole("heading", { name: "평가 범위와 한계" }).closest("section")!;
    const observations = screen.getByRole("heading", { name: "관찰" }).closest("section")!;
    expect(within(observations).getByText("기존 관찰 메모를 그대로 표시한다.")).toBeVisible();
    expect(conclusion.compareDocumentPosition(body) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(method.nextElementSibling).toBe(scope);
    expect(within(scope).getByText("공개 예시만 사용함")).toBeVisible();
    expect(screen.getByRole("button", {name: "기록 편집"})).toBeVisible();
    expect(screen.queryByRole("textbox", {name: "본문"})).not.toBeInTheDocument();
  });

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

    const editor = await openEditor(user);
    const title = within(editor).getByRole("textbox", { name: "제목" });
    await user.clear(title);
    await user.type(title, "내 충돌 초안");
    await user.clear(within(editor).getByRole("textbox", { name: "목적" }));
    await user.type(within(editor).getByRole("textbox", { name: "목적" }), "보존할 목적");
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("다른 변경 사항");
    expect(within(editor).getByRole("textbox", { name: "제목" })).toHaveValue("내 충돌 초안");
    expect(within(editor).getByRole("textbox", { name: "목적" })).toHaveValue("보존할 목적");
    expect(puts).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "저장된 내용 확인" }));
    const latestSnapshot = await screen.findByRole("region", { name: "서버 최신 전체 내용" });
    expect(within(latestSnapshot).getByRole("textbox", { name: "제목" })).toHaveValue("최신 서버 제목");
    expect(within(latestSnapshot).getByRole("combobox", { name: "기록 종류" })).toHaveValue("experiment");
    expect(within(latestSnapshot).getByRole("textbox", { name: "목적" })).toHaveValue("서버 목적");
    expect(within(latestSnapshot).getByRole("textbox", { name: "도메인 분류" })).toHaveValue("research");
    expect(within(latestSnapshot).getByRole("link", { name: "RAG search" })).toHaveAttribute("href", "/workshop/rag/search");
    expect(within(editor).getByRole("textbox", { name: "제목" })).toHaveValue("내 충돌 초안");
    expect(puts).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "현재 내용을 기준으로 편집 계속" }));
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

    const editor = await openEditor(user);
    await user.type(within(editor).getByRole("textbox", { name: "제목" }), " 수정");
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));
    await user.click(await screen.findByRole("button", { name: "저장된 내용 확인" }));
    let latest = await screen.findByRole("region", { name: "서버 최신 전체 내용" });
    expect(within(latest).getByRole("textbox", { name: "제목" })).toHaveValue("최신 메모");
    expect(within(latest).getByRole("combobox", { name: "기록 종류" })).toHaveValue("note");
    await user.click(screen.getByRole("button", { name: "저장된 내용 확인" }));
    await screen.findByRole("heading", { name: "현재 저장된 내용" });

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

    const editor = await openEditor(user);
    await user.clear(within(editor).getByRole("textbox", { name: "제목" }));
    await user.type(within(editor).getByRole("textbox", { name: "제목" }), "보존할 로컬 제목");
    await user.clear(within(editor).getByRole("textbox", { name: "본문" }));
    await user.type(within(editor).getByRole("textbox", { name: "본문" }), "보존할 로컬 본문");
    await user.clear(within(editor).getByRole("textbox", { name: "목적" }));
    await user.type(within(editor).getByRole("textbox", { name: "목적" }), "보존할 로컬 목적");
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));
    await user.click(await screen.findByRole("button", { name: "저장된 내용 확인" }));
    await screen.findByRole("region", { name: "서버 최신 전체 내용" });
    await user.click(screen.getByRole("button", { name: "현재 내용을 기준으로 편집 계속" }));

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

    await openEditor(user);
    const kind = screen.getByRole("combobox", { name: "기록 종류" });
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

  it("archives and restores only after successful responses", async () => {
    const actions: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path.endsWith("/archive")) { actions.push("archive"); return jsonResponse({ ...noteRecord(), revision: 3, archived_at: "2026-09-07T02:00:00Z" }); }
      if (path.endsWith("/restore")) { actions.push("restore"); return jsonResponse({ ...noteRecord(), revision: 4, archived_at: null }); }
      if (path === "/api/v1/learning/records/record-1") return jsonResponse({ ...noteRecord(), revision: 2 });
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    await user.click(await screen.findByRole("button", { name: "기록 보관" }));
    expect(await screen.findByText("보관된 기록입니다. 복원한 뒤 편집할 수 있습니다.")).toBeVisible();
    expect(screen.queryByRole("textbox", { name: "제목" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "기록 복원" }));
    await waitFor(() => expect(actions).toEqual(["archive", "restore"]));
    expect(await screen.findByRole("button", { name: "기록 편집" })).toBeEnabled();
  });

  it("keeps a dirty editing session and its navigation guard mounted while reading saved content", async () => {
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      if (path === "/api/v1/learning/records/record-1") return jsonResponse(experimentRecord(2, "현재 실험"));
      return optionResponse(path);
    }));
    const user = userEvent.setup();
    render(<LearningRecordPage recordId="record-1" />);

    let editor = await openEditor(user);
    await user.clear(within(editor).getByRole("textbox", { name: "제목" }));
    await user.type(within(editor).getByRole("textbox", { name: "제목" }), "보존할 제목");
    await user.clear(within(editor).getByRole("textbox", { name: "본문" }));
    await user.type(within(editor).getByRole("textbox", { name: "본문" }), "보존할 본문");
    await user.clear(within(editor).getByRole("textbox", { name: "목적" }));
    await user.type(within(editor).getByRole("textbox", { name: "목적" }), "보존할 목적");
    await user.click(screen.getByRole("button", { name: "읽기 보기" }));
    const reader = screen.getByRole("region", { name: "기록 읽기" });
    expect(within(reader).getByText("원문 본문")).toBeVisible();
    expect(within(reader).queryByText("보존할 본문")).not.toBeInTheDocument();
    editor = await openEditor(user);
    expect(within(editor).getByRole("textbox", { name: "본문" })).toHaveValue("보존할 본문");
    expect(screen.getByRole("link", { name: "학습 기록 목록" }).dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }))).toBe(false);
    expect(confirm).toHaveBeenCalledTimes(1);

    editor = screen.getByRole("region", { name: "기록 편집" });
    expect(within(editor).getByRole("textbox", { name: "제목" })).toHaveValue("보존할 제목");
    expect(within(editor).getByRole("textbox", { name: "본문" })).toHaveValue("보존할 본문");
    expect(within(editor).getByRole("textbox", { name: "목적" })).toHaveValue("보존할 목적");
    expect(within(editor).getByRole("region", { name: "본문 미리보기" })).toHaveTextContent("보존할 본문");
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

    const editor = await openEditor(user);
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

    const editor = await openEditor(user);
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

    const editor = await openEditor(user);
    await user.clear(within(editor).getByRole("textbox", { name: "제목" }));
    await user.type(within(editor).getByRole("textbox", { name: "제목" }), "보존할 로컬 초안");
    await user.click(screen.getByRole("button", { name: "기록 보관" }));
    await user.click(await screen.findByRole("button", { name: "저장된 내용 확인" }));
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
    await user.click(await screen.findByRole("button", { name: "저장된 내용 확인" }));
    await screen.findByRole("region", { name: "서버 최신 전체 내용" });
    await user.click(screen.getByRole("button", { name: "최신 상태 적용" }));

    expect(screen.getByText("최신 서버 본문")).toBeVisible();
    expect(screen.getByText("서버 목적")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "기록 복원" }));
    const editor = await openEditor(user);
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
    expect(screen.queryByText("rag.search")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "RAG search" })).not.toBeInTheDocument();
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

    await openEditor(user);
    await user.clear(screen.getByRole("textbox", { name: "제목" }));
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

    const editor = await openEditor(user);
    await user.type(within(editor).getByRole("textbox", { name: "제목" }), " 수정");
    await user.click(within(editor).getByRole("button", { name: "변경 저장" }));
    await user.click(await screen.findByRole("button", { name: "저장된 내용 확인" }));
    view.rerender(<LearningRecordPage recordId="record-b" />);
    expect(await screen.findByRole("heading", { name: "새 기록", level: 1 })).toBeVisible();
    await act(async () => oldLatest.resolve(jsonResponse({ ...noteRecord(), id: "record-a", revision: 8, draft: { ...noteRecord().draft, title: "늦은 최신 기록" } })));

    await waitFor(() => expect(screen.queryByText("늦은 최신 기록")).not.toBeInTheDocument());
    expect(screen.queryByRole("heading", { name: "다른 변경 사항이 있습니다" })).not.toBeInTheDocument();
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

async function openEditor(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "기록 편집" }));
  return screen.findByRole("region", { name: "기록 편집" });
}

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
