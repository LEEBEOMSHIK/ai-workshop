import { render, screen } from "@testing-library/react";

import { routes } from "../../../shared/routing/routes";
import LabsRoute, { metadata } from "./page";

describe("LabsRoute", () => {
  it("renders the technology directory separately from the public entrance", () => {
    render(<LabsRoute />);

    expect(
      screen.getByRole("heading", { name: "AI 연구실" }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: "RAG 기술 연구실 들어가기" }),
    ).toHaveAttribute("href", "/labs/rag");
    expect(screen.queryByText("문서 수집 라인")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "AI 기술 관리자들을 만나는 연구소 입구" }),
    ).not.toBeInTheDocument();
  });

  it("declares the Lab floor as its own canonical route", () => {
    expect(metadata.alternates?.canonical).toBe(routes.labs);
  });
});
