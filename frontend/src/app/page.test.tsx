import { render, screen } from "@testing-library/react";

import HomeRoute, { metadata } from "./page";

describe("HomeRoute", () => {
  it("renders the shared public Lab world without a separate Lab CTA", () => {
    render(<HomeRoute />);

    expect(
      screen.getByRole("heading", { name: "AI 기술 관리자들이 일하는 연구소" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }),
    ).toBeVisible();
    expect(screen.queryByRole("link", { name: "AI Lab 둘러보기" })).not.toBeInTheDocument();
  });

  it("declares the public entrance as the canonical route", () => {
    expect(metadata.alternates?.canonical).toBe("/");
  });
});
