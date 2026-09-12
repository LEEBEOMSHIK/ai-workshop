import { render, screen } from "@testing-library/react";

import RagLabRoute from "./page";

vi.mock("../../../../features/publishing/api", () => ({
  listPublicStudies: vi.fn().mockResolvedValue({ items: [] }),
}));

describe("RagLabRoute", () => {
  it("renders the public RAG overview without authentication setup", async () => {
    render(await RagLabRoute());

    expect(
      screen.getByRole("heading", { name: "RAG 기술 연구실" }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", {
        name: "현재 검색 기능 사용하기",
      }),
    ).toBeVisible();
  });
});
