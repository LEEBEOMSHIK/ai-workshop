import { render, screen } from "@testing-library/react";

import { routes } from "../../../shared/routing/routes";
import LabsRoute, { metadata } from "./page";

describe("LabsRoute", () => {
  it("renders the working Lab floor separately from the public entrance", () => {
    render(<LabsRoute />);

    expect(
      screen.getByRole("heading", { name: "AI 기술 관리자들이 일하는 연구소" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }),
    ).toBeVisible();
    expect(screen.getByText("문서 수집 라인")).toBeVisible();
    expect(
      screen.queryByRole("heading", { name: "AI 기술 관리자들을 만나는 연구소 입구" }),
    ).not.toBeInTheDocument();
  });

  it("declares the Lab floor as its own canonical route", () => {
    expect(metadata.alternates?.canonical).toBe(routes.labs);
  });
});
