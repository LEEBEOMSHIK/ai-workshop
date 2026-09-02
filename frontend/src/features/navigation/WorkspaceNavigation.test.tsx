import { render, screen } from "@testing-library/react";

import { routes } from "../../shared/routing/routes";
import { WorkspaceNavigation } from "./WorkspaceNavigation";

describe("WorkspaceNavigation", () => {
  it("links the private workshop navigation to canonical routes", () => {
    render(
      <WorkspaceNavigation
        user={{
          id: "6806a6c1-04c4-4f2c-87d8-8cd1bf06e898",
          display_name: "Owner",
          email: "owner@example.com",
          role: "owner",
        }}
      />,
    );

    expect(screen.getByRole("navigation", { name: "비공개 작업소" })).toBeVisible();
    expect(screen.getByRole("link", { name: "지식 공간" })).toHaveAttribute(
      "href",
      routes.workshopHome,
    );
    expect(screen.getByRole("link", { name: "RAG 검색" })).toHaveAttribute(
      "href",
      routes.workshopRagSearch,
    );
    expect(screen.queryByRole("link", { name: "RAG 구성" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI Lab" })).toHaveAttribute(
      "href",
      routes.labs,
    );
  });
});
