import { render, screen, within } from "@testing-library/react";

import {
  PublicStudyDetail,
  PublicStudyList,
  PublicStudyNotFound,
} from "./PublicStudies";
import { studySnapshot } from "./test-fixtures";

describe("public studies", () => {
  it("renders server totals, topic filters and bounded page navigation preserving the selected query", () => {
    render(<PublicStudyList query={{ page: 50, topic: "rag" }} result={{ status: "ready", items: [studySnapshot()], catalog: { total: 1200, page: 50, page_size: 12, total_pages: 100, topics: [{ key: "rag", count: 1200 }, { key: "new-topic", count: 2 }] } }} />);
    expect(screen.getByText("총 1200개 기록")).toBeVisible();
    expect(screen.getByRole("button", { name: "카테고리: 검색 증강 생성 (1200)" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("link", { name: "new-topic (2)" })).not.toBeInTheDocument();
    const pager = screen.getByRole("navigation", { name: "연구 기록 페이지" });
    expect(within(pager).getByRole("link", { name: "50페이지" })).toHaveAttribute("aria-current", "page");
    expect(within(pager).getAllByRole("link")).toHaveLength(9);
    expect(within(pager).getByRole("link", { name: "다음 페이지" })).toHaveAttribute("href", "/labs/rag/studies?topic=rag&page=51");
    expect(screen.getByRole("link", { name: "하이브리드 검색 실험 읽기" })).toHaveAttribute("href", "/studies/hybrid-search?topic=rag&page=50");
  });

  it("disables both page edges on a one-page result and returns to the same query from detail", () => {
    const { rerender } = render(<PublicStudyList result={{ status: "ready", items: [studySnapshot()], catalog: { total: 1, page: 1, page_size: 12, total_pages: 1, topics: [] } }} />);
    expect(screen.getByLabelText("이전 페이지")).toHaveAttribute("aria-disabled", "true");
    expect(screen.getByLabelText("다음 페이지")).toHaveAttribute("aria-disabled", "true");
    rerender(<PublicStudyDetail snapshot={studySnapshot()} query={{ page: 2, topic: "retrieval" }} />);
    expect(screen.getByRole("link", { name: "공개 연구 기록으로 돌아가기" })).toHaveAttribute("href", "/labs/rag/studies?topic=retrieval&page=2");
  });
  it("makes all card content one native detail link with no nested controls", () => {
    render(<PublicStudyList result={{ status: "ready", items: [studySnapshot()] }} />);
    const card = screen.getByRole("listitem");
    const link = within(card).getByRole("link", { name: "하이브리드 검색 실험 읽기" });
    expect(link.tagName).toBe("A");
    expect(link).toHaveAttribute("href", "/studies/hybrid-search");
    expect(within(link).getByRole("heading", { name: "하이브리드 검색 실험" })).toBeVisible();
    expect(within(card).getAllByText(/하이브리드 검색 실험/)).toHaveLength(1);
    expect(within(card).getAllByRole("link")).toHaveLength(1);
    expect(within(link).getByText("retrieval")).toBeVisible();
    expect(within(link).getByText("rag")).toBeVisible();
    expect(within(link).getByText("검색 기준선 비교")).toBeVisible();
    expect(within(link).queryByRole("link")).not.toBeInTheDocument();
    expect(within(link).queryByRole("button")).not.toBeInTheDocument();
  });

  it("keeps the whole card accessible without a separate read action or eager prefetch", () => {
    render(<PublicStudyList result={{ status: "ready", items: [studySnapshot()] }} />);
    const action = screen.getByRole("link", { name: "하이브리드 검색 실험 읽기" });
    expect(screen.queryByText("기록 읽기 →")).not.toBeInTheDocument();
    expect(action).toHaveAttribute("href", "/studies/hybrid-search");
    expect(action).toHaveAttribute("data-prefetch", "false");
    expect(action).not.toHaveAttribute("aria-hidden");
  });

  it("distinguishes an empty publication list from an unavailable reader", () => {
    const { rerender } = render(<PublicStudyList result={{ status: "ready", items: [] }} />);
    expect(screen.getByText("공개된 연구 기록이 아직 없습니다.")).toBeVisible();

    rerender(<PublicStudyList result={{ status: "unavailable" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("공개 연구 서비스를 불러올 수 없습니다");
  });

  it("links details without eager prefetch", () => {
    render(<PublicStudyList result={{ status: "ready", items: [studySnapshot()] }} />);

    expect(screen.getByRole("link", { name: "하이브리드 검색 실험 읽기" })).toHaveAttribute(
      "href",
      "/studies/hybrid-search",
    );
    expect(screen.getByRole("link", { name: "하이브리드 검색 실험 읽기" })).toHaveAttribute(
      "data-prefetch",
      "false",
    );
  });

  it("uses the same not-found message for missing and withdrawn detail", () => {
    render(<PublicStudyNotFound />);
    expect(screen.getByRole("heading", { name: "연구 기록을 찾을 수 없습니다" })).toBeVisible();
  });

  it("keeps the public detail return action linked to the study list", () => {
    render(<PublicStudyDetail snapshot={studySnapshot()} />);

    const returnLink = screen.getByRole("link", { name: "공개 연구 기록으로 돌아가기" });
    expect(returnLink).toHaveAttribute("href", "/labs/rag/studies");
    expect(returnLink).toBeVisible();
  });

  it("explains the limits of withdrawal on a public detail", () => {
    render(<PublicStudyDetail snapshot={studySnapshot()} />);
    expect(screen.getByText(/이미 열었거나 복사한 내용은 되돌려 회수할 수 없습니다/)).toBeVisible();
  });
});
