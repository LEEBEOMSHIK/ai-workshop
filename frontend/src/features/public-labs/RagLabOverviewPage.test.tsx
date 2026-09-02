import { render, screen } from "@testing-library/react";

import { loginPath, routes } from "../../shared/routing/routes";
import { RagLabOverviewPage } from "./RagLabOverviewPage";

describe("RagLabOverviewPage", () => {
  it("separates verified RAG capability from later public service preparation", () => {
    render(<RagLabOverviewPage />);

    expect(
      screen.getByRole("heading", { name: "RAG 기술 연구실" }),
    ).toBeVisible();
    expect(screen.getByText("BM25 + bi-encoder + RRF")).toBeVisible();
    expect(
      screen.getByText("정확 일치와 의미 일치를 구분한 원문 하이라이트"),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "현재 사용할 수 있는 기능" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "공개 서비스 준비" }),
    ).toBeVisible();
    expect(
      screen.getByRole("heading", { name: "관리 경계" }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", {
        name: "로그인하고 현재 검색 기능 사용하기",
      }),
    ).toHaveAttribute("href", loginPath(routes.workshopRagSearch));
    expect(screen.queryByText(/데모/u)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: /공개 AI 검색/u }),
    ).not.toBeInTheDocument();
  });
});
