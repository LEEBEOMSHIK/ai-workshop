import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { PublicStudyList } from "./PublicStudies";

const topics = [{ key: "rag", count: 12 }, ...Array.from({ length: 100 }, (_, index) => ({ key: `topic-${index}`, count: 2 }))];
function catalog(topic?: string, page = 2) {
  return <PublicStudyList query={{ topic, page }} result={{ status: "ready", items: [], catalog: { total: 12, page, page_size: 12, total_pages: 2, topics } }} />;
}

describe("category picker", () => {
  it("keeps the chevron decorative while exposing the open and closed state on the trigger", async () => {
    const user = userEvent.setup();
    render(catalog());
    const trigger = screen.getByRole("button", { name: "카테고리: 전체" });
    const chevron = trigger.querySelector("svg");
    expect(chevron).toHaveAttribute("aria-hidden", "true");
    expect(chevron).toHaveAttribute("focusable", "false");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    await user.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAccessibleName("카테고리: 전체");
    await user.keyboard("{Escape}");
    expect(trigger).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps a large category catalog hidden until opened and focuses search", async () => {
    const user = userEvent.setup();
    render(catalog());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "topic-99 (2)" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "카테고리: 전체" }));
    expect(screen.getByRole("searchbox", { name: "카테고리 검색" })).toHaveFocus();
    const dialog = screen.getByRole("dialog", { name: "카테고리 선택" });
    expect(within(dialog).getAllByRole("link")).toHaveLength(102);
    expect(within(dialog).getByRole("link", { name: "전체" })).toHaveAttribute("href", "/labs/rag/studies?page=1");
    expect(within(dialog).getByRole("link", { name: "전체" })).toHaveAttribute("aria-current", "true");
    expect(screen.getByText("총 12개 기록")).toBeVisible();
  });

  it("searches display names and keys with trimmed case-insensitive input, clears and keeps reset available", async () => {
    const user = userEvent.setup();
    render(catalog("rag"));
    await user.click(screen.getByRole("button", { name: "카테고리: 검색 증강 생성 (12)" }));
    const search = screen.getByRole("searchbox");
    await user.type(search, "  RAG  ");
    expect(screen.getByRole("link", { name: "검색 증강 생성 (12)" })).toHaveAttribute("aria-current", "true");
    expect(screen.queryByRole("link", { name: "topic-99 (2)" })).not.toBeInTheDocument();
    await user.clear(search);
    await user.type(search, "증강");
    expect(screen.getByRole("link", { name: "검색 증강 생성 (12)" })).toBeVisible();
    await user.clear(search);
    await user.type(search, "없는 분류");
    expect(screen.getByRole("status")).toHaveTextContent("검색 결과가 없습니다");
    expect(screen.getByRole("link", { name: "전체" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "검색어 지우기" }));
    expect(search).toHaveValue("");
    expect(search).toHaveFocus();
    expect(screen.getByRole("link", { name: "topic-99 (2)" })).toHaveAttribute("href", "/labs/rag/studies?topic=topic-99&page=1");
  });

  it("opens by keyboard and restores trigger focus after Escape or close", async () => {
    const user = userEvent.setup();
    render(catalog("rag"));
    const trigger = screen.getByRole("button", { name: "카테고리: 검색 증강 생성 (12)" });
    trigger.focus();
    await user.keyboard("{Enter}");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    await user.keyboard(" ");
    await user.click(screen.getByRole("button", { name: "카테고리 선택 닫기" }));
    expect(trigger).toHaveFocus();
  });

  it("closes on current-category keyboard selection and clears search on reopen", async () => {
    const user = userEvent.setup();
    render(catalog("rag"));
    await user.click(screen.getByRole("button", { name: "카테고리: 검색 증강 생성 (12)" }));
    await user.type(screen.getByRole("searchbox"), "rag");
    const link = screen.getByRole("link", { name: "검색 증강 생성 (12)" });
    // Prevent jsdom's unsupported full-page navigation; keep the real link click handler.
    link.addEventListener("click", (event) => event.preventDefault());
    link.focus();
    await user.keyboard("{Enter}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "카테고리: 검색 증강 생성 (12)" }));
    expect(screen.getByRole("searchbox")).toHaveValue("");
  });

  it("dismisses outside the popup and closes when route props change, preserving unknown selection", async () => {
    const user = userEvent.setup();
    const { rerender } = render(catalog("unknown-topic"));
    await user.click(screen.getByRole("button", { name: "카테고리: unknown-topic" }));
    fireEvent.pointerDown(document.body);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "카테고리: unknown-topic" }));
    rerender(catalog("rag", 1));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "카테고리: 검색 증강 생성 (12)" })).toHaveAttribute("aria-expanded", "false");
  });
});
