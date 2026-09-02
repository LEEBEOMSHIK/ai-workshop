import { render, screen } from "@testing-library/react";

import { HomePage } from "./HomePage";

describe("AI Workshop application shell", () => {
  it("shows canonical workspace and administration links", () => {
    render(<HomePage />);

    expect(screen.getByRole("heading", { name: "AI Workshop" })).toBeVisible();
    expect(screen.getByRole("link", { name: "근거 검색" })).toHaveAttribute(
      "href",
      "/app/rag/search",
    );
    expect(screen.getByRole("link", { name: "RAG 구성" })).toHaveAttribute(
      "href",
      "/app/rag/configurations",
    );
    expect(screen.getByRole("link", { name: "모델 관리" })).toHaveAttribute(
      "href",
      "/admin/rag/models",
    );
  });
});
