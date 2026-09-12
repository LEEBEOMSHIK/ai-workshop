import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";

import { ApiError } from "../../shared/api/client";
import { PublishingAdminPage } from "./PublishingAdminPage";
import { adminStudy } from "./test-fixtures";

afterEach(() => {
  vi.restoreAllMocks();
});

it("shows an explicit 20-item page boundary and current-page filter scope", async () => {
  const api = publishingApi({ list: vi.fn().mockResolvedValue({ items: Array.from({ length: 20 }, (_, index) => adminStudy({ snapshot: { ...adminStudy().snapshot, content: { ...adminStudy().snapshot.content, slug: `study-${index}`, title: `기록 ${index}` } } })) }) });
  render(<PublishingAdminPage api={api} />);

  expect(await screen.findByText("현재 페이지 기준으로 상태를 필터링합니다.")).toBeVisible();
  expect(screen.getByRole("button", { name: "다음 페이지" })).toBeEnabled();
  expect(screen.getByText("1페이지 · 페이지당 20개")).toBeVisible();
});

it("creates a private study and sends the publishing mutation marker", async () => {
  const created = adminStudy();
  const api = publishingApi({ create: vi.fn().mockResolvedValue(created) });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await screen.findByRole("button", { name: "새 기록" });
  await user.click(screen.getByRole("button", { name: "새 기록" }));
  await fillRequiredFields(user);
  await user.click(screen.getByRole("button", { name: "비공개 기록 만들기" }));

  await waitFor(() => expect(api.create).toHaveBeenCalledWith(expect.objectContaining({ slug: "hybrid-search" })));
  expect(screen.getByText("비공개 초안으로 만들었습니다.")).toBeVisible();
});

it("publishes only the exact saved preview and invalidates it after an edit", async () => {
  const saved = adminStudy();
  const api = publishingApi({
    list: vi.fn().mockResolvedValue({ items: [saved] }),
    preview: vi.fn().mockResolvedValue({ snapshot: saved.snapshot, digest: saved.digest }),
    publish: vi.fn().mockResolvedValue({ ...saved, applied_action: "publish", applied_revision: 3 }),
  });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  await user.click(screen.getByRole("button", { name: "서버 미리보기" }));
  expect(await screen.findByText("미리보기 리비전 3")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "미리보기와 같은 버전 공개" }));
  expect(api.publish).toHaveBeenCalledWith("hybrid-search", expect.objectContaining({ expected_revision: 3, expected_digest: "a".repeat(64) }));

  await user.type(screen.getByRole("textbox", { name: "제목" }), " 수정");
  expect(screen.queryByRole("button", { name: "미리보기와 같은 버전 공개" })).not.toBeInTheDocument();
  expect(screen.getByText("편집 후 미리보기가 무효화되었습니다.")).toBeVisible();
});

it("preserves edits on a 409 conflict and offers an explicit reload", async () => {
  const saved = adminStudy();
  const api = publishingApi({
    list: vi.fn().mockResolvedValue({ items: [saved] }),
    update: vi.fn().mockRejectedValue(new ApiError("conflict", 409, "publishing_revision_conflict")),
  });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  const title = screen.getByRole("textbox", { name: "제목" });
  await user.type(title, " 보존");
  await user.click(screen.getByRole("button", { name: "변경 저장" }));

  expect(await screen.findByRole("alert")).toHaveTextContent("다른 변경이 먼저 저장되었습니다");
  expect(title).toHaveValue("하이브리드 검색 실험 보존");
  expect(screen.getByRole("button", { name: "서버 버전 다시 불러오기" })).toBeVisible();
});

it("retains one request id for an ambiguous retry and shows pending as not yet applied", async () => {
  const saved = adminStudy();
  const api = publishingApi({
    list: vi.fn().mockResolvedValue({ items: [saved] }),
    preview: vi.fn().mockResolvedValue({ snapshot: saved.snapshot, digest: saved.digest }),
    publish: vi.fn().mockRejectedValueOnce(new TypeError("network")).mockImplementationOnce((_slug, request) => Promise.resolve(adminStudy({
      delivery_pending: true,
      desired_action: "publish",
      last_request_id: request.request_id,
      delivery_error_code: "publishing_manual_delivery_pending",
      pending_command: { action: "publish", ...request },
    }))),
  });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  await user.click(screen.getByRole("button", { name: "서버 미리보기" }));
  await user.click(await screen.findByRole("button", { name: "미리보기와 같은 버전 공개" }));
  await user.click(await screen.findByRole("button", { name: "같은 공개 요청 다시 시도" }));

  const firstRequest = vi.mocked(api.publish).mock.calls[0]?.[1].request_id;
  const secondRequest = vi.mocked(api.publish).mock.calls[1]?.[1].request_id;
  expect(firstRequest).toBe(secondRequest);
  expect(screen.getByRole("status")).toHaveTextContent("적용 대기");
  expect(screen.queryByText("공개되었습니다.")).not.toBeInTheDocument();
});

it("ignores a stale preview after selecting another record", async () => {
  const first = adminStudy();
  const second = adminStudy({ snapshot: { ...adminStudy().snapshot, content: { ...adminStudy().snapshot.content, slug: "second-study", title: "두 번째 기록" } }, digest: "b".repeat(64) });
  const delayed = deferred<{ snapshot: typeof first.snapshot; digest: string }>();
  const api = publishingApi({ list: vi.fn().mockResolvedValue({ items: [first, second] }), preview: vi.fn().mockImplementation((slug) => slug === "hybrid-search" ? delayed.promise : Promise.resolve({ snapshot: second.snapshot, digest: second.digest })) });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  await user.click(screen.getByRole("button", { name: "서버 미리보기" }));
  await user.click(screen.getByRole("button", { name: /^두 번째 기록 편집/ }));

  expect(screen.getByRole("textbox", { name: "제목" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "서버 미리보기" })).toBeEnabled();
  await act(async () => delayed.resolve({ snapshot: first.snapshot, digest: first.digest }));

  expect(screen.getByRole("textbox", { name: "제목" })).toHaveValue("두 번째 기록");
  expect(screen.getByRole("textbox", { name: "제목" })).toBeEnabled();
  expect(screen.queryByText("미리보기 리비전 3")).not.toBeInTheDocument();
});

it("keeps the new record usable when an old reload finishes late", async () => {
  const first = adminStudy();
  const second = adminStudy({ snapshot: { ...adminStudy().snapshot, content: { ...adminStudy().snapshot.content, slug: "second-study", title: "두 번째 기록" } } });
  const delayed = deferred<typeof first>();
  const api = publishingApi({ list: vi.fn().mockResolvedValue({ items: [first, second] }), detail: vi.fn().mockReturnValue(delayed.promise) });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  await user.click(screen.getByRole("button", { name: "서버 버전 다시 불러오기" }));
  await user.click(screen.getByRole("button", { name: /^두 번째 기록 편집/ }));

  expect(screen.getByRole("textbox", { name: "제목" })).toHaveValue("두 번째 기록");
  expect(screen.getByRole("textbox", { name: "제목" })).toBeEnabled();
  expect(screen.getByRole("button", { name: "서버 미리보기" })).toBeEnabled();
  await act(async () => delayed.resolve(first));
  expect(screen.getByRole("textbox", { name: "제목" })).toHaveValue("두 번째 기록");
  expect(screen.getByRole("textbox", { name: "제목" })).toBeEnabled();
});

it("shows the initial list failure without requiring a selected record", async () => {
  const api = publishingApi({ list: vi.fn().mockRejectedValue(new TypeError("offline")) });

  render(<PublishingAdminPage api={api} />);

  expect(await screen.findByRole("alert")).toHaveTextContent("공개 연구 관리 목록을 불러오지 못했습니다.");
  expect(screen.getByText("편집할 기록을 선택하거나 새 기록을 만드세요.")).toBeVisible();
});

it("asks before replacing dirty content and keeps it when the user declines", async () => {
  const first = adminStudy();
  const second = adminStudy({ snapshot: { ...adminStudy().snapshot, content: { ...adminStudy().snapshot.content, slug: "second-study", title: "두 번째 기록" } } });
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const api = publishingApi({ list: vi.fn().mockResolvedValue({ items: [first, second] }) });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  await user.type(screen.getByRole("textbox", { name: "제목" }), " 보존");
  await user.click(screen.getByRole("button", { name: /^두 번째 기록 편집/ }));

  expect(confirm).toHaveBeenCalled();
  expect(screen.getByRole("textbox", { name: "제목" })).toHaveValue("하이브리드 검색 실험 보존");
});

it("asks before changing pages and keeps dirty content on the current page when declined", async () => {
  const studies = Array.from({ length: 20 }, (_, index) => adminStudy({
    snapshot: {
      ...adminStudy().snapshot,
      content: {
        ...adminStudy().snapshot.content,
        slug: `study-${index}`,
        title: `페이지 기록 ${index}`,
      },
    },
  }));
  const list = vi.fn().mockResolvedValue({ items: studies });
  const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
  const user = userEvent.setup();
  render(<PublishingAdminPage api={publishingApi({ list })} />);

  await user.click((await screen.findAllByRole("button", { name: /편집/ }))[0]!);
  await user.type(screen.getByRole("textbox", { name: "제목" }), " 보존");
  await user.click(screen.getByRole("button", { name: "다음 페이지" }));

  expect(confirm).toHaveBeenCalledOnce();
  expect(list).toHaveBeenCalledOnce();
  expect(screen.getByText("1페이지 · 페이지당 20개")).toBeVisible();
  expect(screen.getByRole("textbox", { name: "제목" })).toHaveValue("페이지 기록 0 보존");
});

it("does not let a stale save response replace a newly selected record", async () => {
  const first = adminStudy();
  const second = adminStudy({ snapshot: { ...adminStudy().snapshot, content: { ...adminStudy().snapshot.content, slug: "second-study", title: "두 번째 기록" } } });
  const delayed = deferred<typeof first>();
  vi.spyOn(window, "confirm").mockReturnValue(true);
  const api = publishingApi({ list: vi.fn().mockResolvedValue({ items: [first, second] }), update: vi.fn().mockReturnValue(delayed.promise) });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  await user.type(screen.getByRole("textbox", { name: "제목" }), " 이전 요청");
  await user.click(screen.getByRole("button", { name: "변경 저장" }));
  await user.click(screen.getByRole("button", { name: /^두 번째 기록 편집/ }));
  await act(async () => delayed.resolve(first));

  expect(screen.getByRole("textbox", { name: "제목" })).toHaveValue("두 번째 기록");
});

it("hydrates the exact pending command after selecting a reloaded study", async () => {
  const pending = adminStudy({
    delivery_pending: true,
    desired_action: "withdraw",
    pending_command: {
      action: "withdraw",
      expected_revision: 2,
      expected_digest: "c".repeat(64),
      request_id: "persisted-withdraw-request",
    },
  });
  const applied = adminStudy({ applied_action: "withdraw", applied_sequence: 2 });
  const api = publishingApi({
    list: vi.fn().mockResolvedValue({ items: [pending] }),
    withdraw: vi.fn().mockResolvedValue(applied),
  });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  await user.click(screen.getByRole("button", { name: "같은 철회 요청 다시 시도" }));

  expect(api.withdraw).toHaveBeenCalledWith("hybrid-search", {
    expected_revision: 2,
    expected_digest: "c".repeat(64),
    request_id: "persisted-withdraw-request",
  });
});

it("hydrates the exact pending command returned by an explicit refresh", async () => {
  const saved = adminStudy();
  const pending = adminStudy({
    delivery_pending: true,
    desired_action: "publish",
    pending_command: {
      action: "publish",
      expected_revision: 3,
      expected_digest: "a".repeat(64),
      request_id: "refresh-publish-request",
    },
  });
  const api = publishingApi({
    list: vi.fn().mockResolvedValue({ items: [saved] }),
    detail: vi.fn().mockResolvedValue(pending),
  });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  await user.click(screen.getByRole("button", { name: "서버 버전 다시 불러오기" }));

  expect(await screen.findByRole("button", { name: "같은 공개 요청 다시 시도" })).toBeEnabled();
  expect(screen.getByText("공개 요청 리비전 3")).toBeVisible();
});

it("rehydrates an older exact pending command after saving a newer draft", async () => {
  const pending = adminStudy({
    delivery_pending: true,
    desired_action: "publish",
    pending_command: {
      action: "publish",
      expected_revision: 3,
      expected_digest: "a".repeat(64),
      request_id: "persisted-publish-request",
    },
  });
  const advanced = adminStudy({
    snapshot: { ...adminStudy().snapshot, revision: 4, content: { ...adminStudy().snapshot.content, title: "새 편집본" } },
    digest: "d".repeat(64),
    delivery_pending: true,
    desired_action: "publish",
    pending_command: pending.pending_command,
  });
  const api = publishingApi({
    list: vi.fn().mockResolvedValue({ items: [pending] }),
    update: vi.fn().mockResolvedValue(advanced),
    publish: vi.fn().mockResolvedValue({ ...advanced, delivery_pending: false, pending_command: null, applied_action: "publish", applied_revision: 3 }),
  });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  await user.clear(screen.getByRole("textbox", { name: "제목" }));
  await user.type(screen.getByRole("textbox", { name: "제목" }), "새 편집본");
  await user.click(screen.getByRole("button", { name: "변경 저장" }));
  await user.click(await screen.findByRole("button", { name: "같은 공개 요청 다시 시도" }));

  expect(api.publish).toHaveBeenCalledWith("hybrid-search", expect.objectContaining({
    expected_revision: 3,
    expected_digest: "a".repeat(64),
    request_id: "persisted-publish-request",
  }));
});

it("keeps an ambiguous in-session command while edits are dirty and requires resolution first", async () => {
  const saved = adminStudy();
  const api = publishingApi({
    list: vi.fn().mockResolvedValue({ items: [saved] }),
    preview: vi.fn().mockResolvedValue({ snapshot: saved.snapshot, digest: saved.digest }),
    publish: vi.fn().mockRejectedValue(new TypeError("network")),
  });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  await user.click(screen.getByRole("button", { name: "서버 미리보기" }));
  await user.click(await screen.findByRole("button", { name: "미리보기와 같은 버전 공개" }));
  await user.type(screen.getByRole("textbox", { name: "제목" }), " 새 편집");

  expect(screen.getByRole("button", { name: "같은 공개 요청 다시 시도" })).toBeDisabled();
  expect(screen.getByText(/편집 내용을 먼저 저장하거나 되돌려야/)).toBeVisible();
  expect(screen.getByRole("textbox", { name: "제목" })).toHaveValue("하이브리드 검색 실험 새 편집");
});

it("prevents switching records or creating while a publication command is in flight", async () => {
  const first = adminStudy();
  const second = adminStudy({
    snapshot: {
      ...adminStudy().snapshot,
      content: {
        ...adminStudy().snapshot.content,
        slug: "second-study",
        title: "두 번째 기록",
      },
    },
  });
  const command = deferred<typeof first>();
  const api = publishingApi({
    list: vi.fn().mockResolvedValue({ items: [first, second] }),
    preview: vi.fn().mockResolvedValue({ snapshot: first.snapshot, digest: first.digest }),
    publish: vi.fn().mockReturnValue(command.promise),
  });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  await user.click(screen.getByRole("button", { name: "서버 미리보기" }));
  await user.click(await screen.findByRole("button", { name: "미리보기와 같은 버전 공개" }));

  expect(screen.getByRole("button", { name: /^두 번째 기록 편집/ })).toBeDisabled();
  expect(screen.getByRole("button", { name: "새 기록" })).toBeDisabled();

  await act(async () => command.reject(new TypeError("network")));
  expect(await screen.findByRole("alert")).toHaveTextContent("요청 결과를 확인하지 못했습니다");
});

it("keeps an ambiguous command identity by preventing editor replacement after failure", async () => {
  const first = adminStudy();
  const second = adminStudy({
    snapshot: {
      ...adminStudy().snapshot,
      content: {
        ...adminStudy().snapshot.content,
        slug: "second-study",
        title: "두 번째 기록",
      },
    },
  });
  const api = publishingApi({
    list: vi.fn().mockResolvedValue({ items: [first, second] }),
    preview: vi.fn().mockResolvedValue({ snapshot: first.snapshot, digest: first.digest }),
    publish: vi.fn().mockRejectedValue(new TypeError("network")),
  });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  await user.click(screen.getByRole("button", { name: "서버 미리보기" }));
  await user.click(await screen.findByRole("button", { name: "미리보기와 같은 버전 공개" }));
  await screen.findByRole("alert");

  const secondButton = screen.getByRole("button", { name: /^두 번째 기록 편집/ });
  expect(secondButton).toBeDisabled();
  expect(screen.getByRole("button", { name: "새 기록" })).toBeDisabled();
  await user.click(secondButton);
  expect(screen.getByRole("textbox", { name: "제목" })).toHaveValue("하이브리드 검색 실험");
  expect(screen.getByRole("button", { name: "같은 공개 요청 다시 시도" })).toBeEnabled();
});

it("describes command success from the returned current state rather than the old action", async () => {
  const saved = adminStudy();
  const currentlyWithdrawn = adminStudy({
    desired_action: "withdraw",
    applied_action: "withdraw",
    applied_sequence: 2,
    sequence: 2,
  });
  const api = publishingApi({
    list: vi.fn().mockResolvedValue({ items: [saved] }),
    preview: vi.fn().mockResolvedValue({ snapshot: saved.snapshot, digest: saved.digest }),
    publish: vi.fn().mockResolvedValue(currentlyWithdrawn),
  });
  const user = userEvent.setup();
  render(<PublishingAdminPage api={api} />);
  await user.click(await screen.findByRole("button", { name: /^하이브리드 검색 실험 편집/ }));
  await user.click(screen.getByRole("button", { name: "서버 미리보기" }));
  await user.click(await screen.findByRole("button", { name: "미리보기와 같은 버전 공개" }));

  expect(await screen.findByRole("status")).toHaveTextContent("비공개 전환이 적용되었습니다");
  expect(screen.queryByText("공개되었습니다.")).not.toBeInTheDocument();
});

it("reminds the owner that privacy review is manual rather than automatic redaction", async () => {
  render(<PublishingAdminPage api={publishingApi()} />);

  expect(await screen.findByText(/비공개 원문, 자격 증명, 개인정보를 직접 확인해 제외/)).toBeVisible();
  expect(screen.getByText(/자동 비식별화나 자동 삭제가 아닙니다/)).toBeVisible();
});

function publishingApi(overrides: Record<string, unknown> = {}) {
  return {
    list: vi.fn().mockResolvedValue({ items: [] }),
    personas: vi.fn().mockResolvedValue({ items: [] }),
    detail: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    preview: vi.fn(),
    publish: vi.fn(),
    withdraw: vi.fn(),
    ...overrides,
  };
}

async function fillRequiredFields(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByRole("textbox", { name: "공개 주소 슬러그" }), "hybrid-search");
  await user.type(screen.getByRole("textbox", { name: "제목" }), "하이브리드 검색 실험");
  await user.type(screen.getByRole("textbox", { name: "요약" }), "검색 기준선 비교");
  await user.type(screen.getByRole("textbox", { name: "기술 주제 키" }), "retrieval, rag");
  await user.type(screen.getByRole("textbox", { name: "본문" }), "실험 본문");
  await user.type(screen.getByRole("textbox", { name: "검증 기록" }), "재현 완료");
  await user.type(screen.getByRole("textbox", { name: "남은 한계" }), "표본이 작음");
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((done, fail) => {
    resolve = done;
    reject = fail;
  });
  return { promise, reject, resolve };
}
