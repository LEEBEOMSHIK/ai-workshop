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
    expect(screen.getByRole("link", { name: "파일함" })).toHaveAttribute(
      "href",
      routes.workshopHome,
    );
    expect(screen.getByRole("link", { name: "RAG 대화" })).toHaveAttribute(
      "href",
      routes.workshopRagSearch,
    );
    expect(screen.getByRole("link", { name: "학습 기록" })).toHaveAttribute(
      "href",
      routes.workshopLearning,
    );
    expect(screen.queryByRole("link", { name: "RAG 구성" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI Lab" })).toHaveAttribute(
      "href",
      routes.labs,
    );
  });

  it("shows learning records to a member without exposing owner administration", () => {
    render(
      <WorkspaceNavigation
        user={{
          id: "2bfa26a6-acde-4c54-8e44-e713c20e69d4",
          display_name: "Member",
          email: "member@example.com",
          role: "member",
        }}
      />,
    );

    expect(screen.getByRole("link", { name: "학습 기록" })).toHaveAttribute(
      "href",
      "/workshop/learning",
    );
    expect(screen.queryByRole("link", { name: "관리자" })).not.toBeInTheDocument();
  });
});
