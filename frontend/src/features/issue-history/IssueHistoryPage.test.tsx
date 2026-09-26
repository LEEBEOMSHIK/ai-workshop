import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { IssueHistoryPage } from "./IssueHistoryPage";
import { IssueManagement } from "./IssueManagement";
import type { Category, IssueDetail } from "./types";
import { ApiError, apiRequest } from "../../shared/api/client";
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("../../shared/api/client", async (original) => ({ ...await original<typeof import('../../shared/api/client')>(), apiRequest: vi.fn() }));
const category = { id: "cat", code: "ui", name: "대화 화면", sort_order: 0, is_active: true, revision: 1 } as Category;
const issue = { id: "issue", issue_key: "TEST-1", category_id: "cat", title: "화면 개선", status: "implemented", symptom: "화면이 큼", cause: "높이 설정", resolution: "줄임", verification: ["단위 검증"], remaining: ["실제 확인"], commits: [], revision: 1, created_at: "2026-09-27", updated_at: "2026-09-27", events: [], documents: [{ document_id: "doc", version: 1, current_version: 2, title: "설계 기록", source_path: "docs/example.md", sort_order: 0 }] } as IssueDetail;
it("shows Korean categories and pinned versions separately from current versions", () => {
    render(<IssueHistoryPage list={{ items: [issue], total: 1, status_counts: { open: 0, implemented: 1, verified: 0 } }} categories={[category]} selected={issue} filters={{}}/>);
    expect(screen.getByRole("option", { name: "대화 화면" })).toBeVisible();
    const detail = screen.getByRole("region", { name: "문제 상세" });
    expect(within(detail).getByText("실제 확인")).toBeVisible();
    expect(within(detail).getByRole("link", { name: "설계 기록 · 버전 1" })).toHaveAttribute("href", "/admin/system/issues?issue=issue&document_id=doc&version=1");
    expect(within(detail).getByText(/현재 버전 2/)).toBeVisible();
});
it("submits server search with filters and shows total separately from filtered count", () => {
    render(<IssueHistoryPage list={{ items: [], total: 0, status_counts: { open: 5, implemented: 1, verified: 2 } }} categories={[category]} selected={null} filters={{ q: "abc" }}/>);
    expect(screen.getByRole("searchbox")).toHaveValue("abc");
    expect(screen.getByRole("searchbox").closest("form")).toHaveAttribute("action", "/admin/system/issues");
    expect(screen.getByText("조건에 맞는 문제 0개 · 전체 8개")).toBeVisible();
});
it("preserves failed input and request id when retrying a mutation", async () => {
    vi.mocked(apiRequest).mockImplementation(async (path) => { if (path.endsWith("/documents"))
        return { items: [] }; throw new Error("일시 오류"); });
    const user = userEvent.setup();
    render(<IssueManagement categories={[category]} issue={issue} onSaved={vi.fn()}/>);
    await user.click(screen.getByText("카테고리 관리"));
    await user.click(screen.getByText("카테고리 등록"));
    await user.type(screen.getByLabelText("고유 코드"), "new");
    await user.type(screen.getByLabelText("카테고리 이름"), "새 분류");
    const form = screen.getByLabelText("고유 코드").closest("form")!;
    await user.click(within(form).getByRole("button", { name: "저장" }));
    expect(await within(form).findByRole("alert")).toHaveTextContent("일시 오류");
    expect(screen.getByLabelText("카테고리 이름")).toHaveValue("새 분류");
    await user.click(within(form).getByRole("button", { name: "저장" }));
    const calls = vi.mocked(apiRequest).mock.calls.filter(([path]) => path.endsWith("/categories"));
    expect(calls).toHaveLength(2);
    expect(calls[0][1]?.json).toEqual(calls[1][1]?.json);
});
it("keeps the original revision when refreshed data arrives during editing", async () => {
    vi.mocked(apiRequest).mockClear();
    vi.mocked(apiRequest).mockImplementation(async (path) => { if (path.endsWith("/documents"))
        return { items: [] }; throw new Error("conflict"); });
    const user = userEvent.setup();
    const { rerender } = render(<IssueManagement categories={[category]} issue={issue} onSaved={vi.fn()}/>);
    await user.click(screen.getByText("선택한 문제 편집"));
    const title = screen.getAllByLabelText("문제 제목")[1];
    await user.clear(title);
    await user.type(title, "작성 중");
    rerender(<IssueManagement categories={[category]} issue={{ ...issue, revision: 2, title: "다른 변경" }} onSaved={vi.fn()}/>);
    const form = title.closest("form")!;
    await user.click(within(form).getByRole("button", { name: "저장" }));
    const call = vi.mocked(apiRequest).mock.calls.find(([path]) => path.endsWith("/issues/issue"));
    expect(call?.[1]?.json).toMatchObject({ expected_revision: 1, title: "작성 중" });
});
it("advances the expected revision after successful saves", async () => {
    vi.mocked(apiRequest).mockClear();
    vi.mocked(apiRequest).mockImplementation(async (path) => path.endsWith("/documents") ? { items: [] } : {});
    const user = userEvent.setup();
    const { rerender } = render(<IssueManagement categories={[category]} issue={issue} onSaved={vi.fn()}/>);
    await user.click(screen.getByText("선택한 문제 편집"));
    const title = screen.getAllByLabelText("문제 제목")[1];
    const form = title.closest("form")!;
    await user.click(within(form).getByRole("button", { name: "저장" }));
    rerender(<IssueManagement categories={[category]} issue={{ ...issue, revision: 2 }} onSaved={vi.fn()}/>);
    await user.type(title, " 두 번째");
    await user.click(within(form).getByRole("button", { name: "저장" }));
    const calls = vi.mocked(apiRequest).mock.calls.filter(([path]) => path.endsWith("/issues/issue"));
    expect(calls[0][1]?.json).toMatchObject({ expected_revision: 1 });
    expect(calls[1][1]?.json).toMatchObject({ expected_revision: 2 });
});
it("offers explicit reload after conflict without clearing entered text", async () => {
 vi.mocked(apiRequest).mockImplementation(async path => {
  if (path.endsWith("/documents")) return {items: []};
  throw new ApiError("stale", 409, "revision_conflict");
 });
 const user = userEvent.setup();
 render(<IssueManagement categories={[category]} issue={issue} onSaved={vi.fn()} />);
 await user.click(screen.getByText("선택한 문제 편집"));
 const title = screen.getAllByLabelText("문제 제목")[1];
 await user.type(title, " 보존");
 const form = title.closest("form")!;
 await user.click(within(form).getByRole("button", {name: "저장"}));
 expect(await within(form).findByRole("alert")).toHaveTextContent("충돌했습니다");
 expect(title).toHaveValue("화면 개선 보존");
 expect(within(form).getByRole("button", {name: "최신 내용 다시 열기 (입력 초기화)"})).toBeVisible();
});
