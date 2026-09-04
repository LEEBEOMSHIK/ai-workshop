import { render, screen } from "@testing-library/react";

import { loadPublicLabCatalog } from "./catalog";
import { LabWorldPage } from "./LabWorldPage";

describe("LabWorldPage", () => {
  it("renders one working station for each validated public Lab", () => {
    const ready = loadPublicLabCatalog();
    render(<LabWorldPage catalog={ready} />);

    expect(
      screen.getByRole("heading", { name: "AI 기술 관리자들이 일하는 연구소" }),
    ).toBeVisible();
    expect(screen.getByRole("region", { name: "RAG 기술 연구실" })).toBeVisible();
    expect(
      screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }),
    ).toBeVisible();
    expect(screen.getByText("RAG 기술 연구실")).toBeVisible();
    expect(screen.getByText("연구 중")).toBeVisible();
    expect(screen.getAllByRole("article")).toHaveLength(1);
  });

  it("keeps public navigation available when no published Labs exist", () => {
    render(<LabWorldPage catalog={{ status: "ready", labs: [] }} />);

    expect(screen.getByText("현재 공개된 연구실을 준비하고 있습니다")).toBeVisible();
    expect(screen.getByRole("navigation", { name: "공개 전시실" })).toBeVisible();
    expect(screen.queryByText("RAG 기술 연구실")).not.toBeInTheDocument();
  });

  it("renders an honest error without a hardcoded Lab fallback", () => {
    render(<LabWorldPage catalog={{ status: "error", labs: [] }} />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "연구실 정보를 불러오지 못했습니다",
    );
    expect(screen.getByRole("navigation", { name: "공개 전시실" })).toBeVisible();
    expect(screen.queryByText("RAG 기술 연구실")).not.toBeInTheDocument();
  });
});
