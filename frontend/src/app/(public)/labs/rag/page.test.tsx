import { render, screen } from "@testing-library/react";

import RagLabRoute from "./page";

describe("RagLabRoute", () => {
  it("renders the public RAG overview synchronously without authentication setup", () => {
    render(RagLabRoute());

    expect(
      screen.getByRole("heading", { name: "RAG 기술 연구실" }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", {
        name: "로그인하고 현재 검색 기능 사용하기",
      }),
    ).toBeVisible();
  });
});
