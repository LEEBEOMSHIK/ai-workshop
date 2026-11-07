import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { LearningListPage } from "./LearningListPage";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
function setup() {
  const paths: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const path = String(input);
    const value = path.includes("topics") ? [{ key: "rag", label: "RAG" }] : path.includes("evaluation-runs") ? [] : { items: [], next_cursor: "next" };
    if (path.includes("learning/records")) paths.push(path);
    return new Response(JSON.stringify(value), { status: 200 });
  }));
  render(<LearningListPage />);
  return paths;
}

it("places creation in the page header and page size beside the bottom pagination", async () => {
  setup(); const user = userEvent.setup();
  await screen.findByText("조건에 맞는 학습 기록이 없습니다.");
  const heading = screen.getByRole("heading", { name: "학습 기록", level: 1 });
  const header = heading.closest("header")!;
  expect(within(header).getByRole("button", { name: "새 기록" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "내 기록" })).not.toBeInTheDocument();
  expect(screen.queryByText("학습 기록을 저장해도 모델 학습, 외부 전송 또는 공개가 실행되지는 않습니다.")).not.toBeInTheDocument();
  const pagination = screen.getByRole("navigation", { name: "학습 기록 페이지" });
  expect(within(pagination.parentElement!).getByRole("combobox", { name: "페이지당 표시" })).toBeVisible();
  await user.click(within(header).getByRole("button", { name: "새 기록" }));
  expect(screen.getByText("학습 기록을 저장해도 모델 학습, 외부 전송 또는 공개가 실행되지는 않습니다.")).toBeVisible();
});

it("keeps detail filters closed and expands without fetching or losing selection", async () => {
  const paths = setup(); const user = userEvent.setup();
  await screen.findByText("조건에 맞는 학습 기록이 없습니다.");
  expect(screen.queryByRole("combobox", { name: "주제 필터" })).not.toBeInTheDocument();
  expect(screen.getByRole("combobox", { name: "정렬" })).toBeVisible();
  expect(screen.getByRole("combobox", { name: "페이지당 표시" })).toBeVisible();
  const toggle = screen.getByRole("button", { name: /상세 필터/ });
  const count = paths.length;
  await user.click(toggle);
  expect(toggle).toHaveAttribute("aria-expanded", "true");
  expect(paths).toHaveLength(count);
  await user.selectOptions(screen.getByRole("combobox", { name: "주제 필터" }), "rag");
  await waitFor(() => expect(paths.at(-1)).toContain("topic_key=rag"));
  await user.click(toggle);
  expect(screen.getByLabelText("적용된 필터")).toHaveTextContent("RAG");
  await user.click(toggle);
  expect(screen.getByRole("combobox", { name: "주제 필터" })).toHaveValue("rag");
});

it("resets only detail filters and pagination while keeping sort and page size", async () => {
  const paths = setup(); const user = userEvent.setup();
  await screen.findByText("조건에 맞는 학습 기록이 없습니다.");
  await user.selectOptions(screen.getByRole("combobox", { name: "정렬" }), "updated");
  await user.selectOptions(screen.getByRole("combobox", { name: "페이지당 표시" }), "10");
  await user.click(screen.getByRole("button", { name: /상세 필터/ }));
  await user.selectOptions(screen.getByRole("combobox", { name: "주제 필터" }), "rag");
  await user.selectOptions(screen.getByRole("combobox", { name: "종류 필터" }), "experiment");
  await user.selectOptions(screen.getByRole("combobox", { name: "보관 상태" }), "all");
  await waitFor(() => expect(screen.getByRole("button", { name: "다음 페이지" })).toBeEnabled());
  await user.click(screen.getByRole("button", { name: "다음 페이지" }));
  await waitFor(() => expect(paths.at(-1)).toContain("cursor=next"));
  await user.click(screen.getByRole("button", { name: /상세 필터/ }));
  await user.click(screen.getByRole("button", { name: "필터 초기화" }));
  await waitFor(() => expect(Object.fromEntries(new URL(paths.at(-1)!, "http://test").searchParams)).toEqual({ sort: "updated", limit: "10", archived: "false" }));
  expect(screen.getByRole("button", { name: "이전 페이지" })).toBeDisabled();
  expect(screen.queryByRole("button", { name: "필터 초기화" })).not.toBeInTheDocument();
});
