import { render, screen, within } from "@testing-library/react";

import { loadPublicLabCatalog } from "./catalog";
import { LabWorldPage } from "./LabWorldPage";

describe("LabWorldPage", () => {
  it("renders a direct full-card link with the validated lab description, status and manager", () => {
    const ready = loadPublicLabCatalog();
    render(<LabWorldPage catalog={ready} />);

    expect(
      screen.getByRole("heading", { name: "AI 연구실" }),
    ).toBeVisible();
    expect(
      screen.getByRole("status", { name: "공개 연구실 상태" }),
    ).toHaveTextContent(`현재 공개된 연구실 ${ready.labs.length}곳`);
    const available = screen.getByRole("region", { name: "연구실 둘러보기" });
    const link = within(available).getByRole("link", { name: "RAG 기술 연구실 들어가기" });
    expect(link).toHaveAttribute("href", "/labs/rag");
    expect(link).toHaveAttribute("data-prefetch", "false");
    expect(within(link).getByRole("heading", { name: "RAG 기술 연구실" })).toBeVisible();
    expect(within(link).getByText("문서를 찾고 원문 근거와 함께 답하는 AI 검색 기술을 연구합니다.")).toBeVisible();
    expect(within(link).getByText("연구 중")).toBeVisible();
    expect(within(link).getByText(/RAG 총괄/)).toBeVisible();
    expect(within(available).getAllByRole("link")).toHaveLength(1);
    expect(within(available).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByText("문서 수집 라인")).not.toBeInTheDocument();
    expect(screen.queryByText("검색 코어")).not.toBeInTheDocument();
    expect(screen.queryByText("근거 검증 모니터")).not.toBeInTheDocument();
  });

  it("shows preparing rooms separately without navigation or interactive controls", () => {
    render(<LabWorldPage catalog={loadPublicLabCatalog()} />);
    const preparing = screen.getByRole("region", { name: "준비 중인 연구실" });
    expect(within(preparing).getByRole("heading", { name: "파인튜닝 연구소" })).toBeVisible();
    expect(within(preparing).getByRole("heading", { name: "AI 공부실" })).toBeVisible();
    expect(within(preparing).getByRole("heading", { name: "온톨로지 연구소" })).toBeVisible();
    expect(within(preparing).getAllByText("관리자 모집 중 · 기능 준비 중")).toHaveLength(3);
    expect(within(preparing).queryByRole("link")).not.toBeInTheDocument();
    expect(within(preparing).queryByRole("button")).not.toBeInTheDocument();
  });

  it("uses each validated technology's own content without inheriting RAG equipment", () => {
    const ready = loadPublicLabCatalog({ labs: [{
      slug: "vision", name: "이미지 연구실", eyebrow: "VISION", description: "이미지를 연구합니다.",
      status: "service", statusLabel: "서비스 중", href: "/labs/vision",
      manager: { name: "이미지 관리자", role: "이미지 분석", intro: "소개", invitation: "초대", ctaLabel: "입장" },
    }] });
    render(<LabWorldPage catalog={ready} />);
    const link = screen.getByRole("link", { name: "이미지 연구실 들어가기" });
    expect(link).toHaveAttribute("href", "/labs/vision");
    expect(within(link).getByText("이미지를 연구합니다.")).toBeVisible();
    expect(within(link).getByText("서비스 중")).toBeVisible();
    expect(within(link).getByText(/이미지 관리자/)).toBeVisible();
    expect(screen.queryByText("RAG 기술 연구실")).not.toBeInTheDocument();
    expect(screen.queryByText("문서 수집 라인")).not.toBeInTheDocument();
  });

  it("keeps public navigation available when no published Labs exist", () => {
    render(<LabWorldPage catalog={{ status: "ready", labs: [] }} />);

    expect(screen.getByText("현재 공개된 연구실을 준비하고 있습니다")).toBeVisible();
    expect(
      screen.getByRole("status", { name: "공개 연구실 상태" }),
    ).toHaveTextContent("현재 공개된 연구실 0곳");
    expect(screen.getByRole("navigation", { name: "공개 전시실" })).toBeVisible();
    expect(screen.queryByText("RAG 기술 연구실")).not.toBeInTheDocument();
  });

  it("renders an honest error without a hardcoded Lab fallback", () => {
    render(<LabWorldPage catalog={{ status: "error", labs: [] }} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "연구실 정보를 불러오지 못했습니다",
    );
    expect(
      screen.getByRole("status", { name: "공개 연구실 상태" }),
    ).toHaveTextContent("공개 연구실 상태를 확인할 수 없습니다");
    expect(screen.getByRole("navigation", { name: "공개 전시실" })).toBeVisible();
    expect(screen.queryByText("RAG 기술 연구실")).not.toBeInTheDocument();
  });
});
