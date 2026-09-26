import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it } from "vitest";

import { IssueHistoryPage } from "./IssueHistoryPage";
import type { IssueLedger } from "./types";

const ledger: IssueLedger = {
  schema_version: 1, updated_at: "2026-09-27", visibility: "internal",
  issues: [
    { id: "TEST-001", title: "빈 대화 생성", area: "conversation", status: "open", symptom: "빈 대화가 남습니다.", cause: "첨부 시 생성됩니다.", resolution: "첫 질문에 생성합니다.", verification: ["재현 확인"], remaining: ["초안 구현"], evidence: ["docs/example.md"], commits: [], history: [{ date: "2026-09-27", event: "원인 확인" }] },
    { id: "TEST-002", title: "문서 선택 크기", area: "ui", status: "implemented", symptom: "화면이 큽니다.", cause: "최소 높이가 큽니다.", resolution: "모달 높이 조정", verification: ["단위 테스트 통과"], remaining: ["모바일 실제 확인"], evidence: ["docs/ui.md"], commits: ["abc1234"], history: [{ date: "2026-09-26", event: "수정 반영" }] },
    { id: "TEST-003", title: "검색 지연", area: "search", status: "verified", symptom: "느립니다.", cause: "중복 계산", resolution: "계산 재사용", verification: ["실제 응답 확인"], remaining: [], evidence: [], commits: [], history: [] },
  ],
};

it("selects an initial issue and distinguishes implementation from verification", () => {
  render(<IssueHistoryPage ledger={ledger} initialIssueId="TEST-002" />);
  const detail = screen.getByRole("region", { name: "문제 상세" });
  expect(within(detail).getByRole("heading", { name: "문서 선택 크기" })).toBeVisible();
  expect(within(detail).getByText("구현됨 · 검증 남음")).toBeVisible();
  expect(within(detail).getByText("모바일 실제 확인")).toBeVisible();
  expect(within(detail).getByRole("link", { name: "docs/ui.md" })).toHaveAttribute("href", "/admin/system/issues?issue=TEST-002&document=0");
  expect(within(detail).getByText("abc1234").tagName).toBe("CODE");
});

it("searches causes and combines status and area filters", async () => {
  const user = userEvent.setup();
  render(<IssueHistoryPage ledger={ledger} />);
  await user.type(screen.getByRole("searchbox", { name: "문제 검색" }), "최소 높이");
  expect(screen.getByRole("button", { name: /TEST-002 문서 선택 크기/ })).toBeVisible();
  expect(screen.queryByRole("button", { name: /TEST-001 빈 대화 생성/ })).not.toBeInTheDocument();
  await user.clear(screen.getByRole("searchbox", { name: "문제 검색" }));
  await user.selectOptions(screen.getByLabelText("처리 상태"), "verified");
  await user.selectOptions(screen.getByLabelText("영역"), "ui");
  expect(screen.getByText("조건에 맞는 문제가 없습니다.")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "필터 초기화" }));
  await user.click(screen.getByRole("button", { name: /TEST-001 빈 대화 생성/ }));
  expect(within(screen.getByRole("region", { name: "문제 상세" })).getByText("원인 확인")).toBeVisible();
});

it("handles an empty ledger without claiming resolution", () => {
  render(<IssueHistoryPage ledger={{ ...ledger, issues: [] }} />);
  expect(screen.getByText("등록된 문제 이력이 없습니다.")).toBeVisible();
  expect(screen.queryByRole("region", { name: "문제 상세" })).not.toBeInTheDocument();
});
