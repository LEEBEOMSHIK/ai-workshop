import { render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { routes } from "./router";

describe("AI Workshop application shell", () => {
  it("shows the workshop heading on the home route", async () => {
    const router = createMemoryRouter(routes, { initialEntries: ["/"] });

    render(<RouterProvider router={router} />);

    expect(
      await screen.findByRole("heading", { name: "AI Workshop" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "근거 검색" })).toHaveAttribute(
      "href",
      "/rag/search",
    );
    expect(screen.getByRole("link", { name: "RAG 구성" })).toHaveAttribute(
      "href",
      "/rag/configurations",
    );
    expect(screen.getByRole("link", { name: "모델 관리" })).toHaveAttribute(
      "href",
      "/rag/models",
    );
  });
});
