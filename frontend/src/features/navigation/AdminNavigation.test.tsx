import { render, screen } from "@testing-library/react";

import { routes } from "../../shared/routing/routes";
import { AdminNavigation } from "./AdminNavigation";

describe("AdminNavigation", () => {
  it("links administration and the private workshop to canonical routes", () => {
    render(
      <AdminNavigation
        user={{
          id: "6806a6c1-04c4-4f2c-87d8-8cd1bf06e898",
          display_name: "Owner",
          email: "owner@example.com",
          role: "owner",
        }}
      />,
    );

    expect(screen.getByRole("link", { name: "RAG 구성" })).toHaveAttribute(
      "href",
      routes.adminRagConfigurations,
    );
    expect(screen.getByRole("link", { name: "RAG 모델" })).toHaveAttribute(
      "href",
      routes.adminRagModels,
    );
    expect(screen.getByRole("link", { name: "비공개 작업소" })).toHaveAttribute(
      "href",
      routes.workshopHome,
    );
  });
});
