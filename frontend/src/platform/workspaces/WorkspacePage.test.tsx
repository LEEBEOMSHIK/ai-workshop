import { render, screen } from "@testing-library/react";

import { WorkspacePage } from "./WorkspacePage";

describe("WorkspacePage", () => {
  it("shows company personal and temporary spaces without a team creation choice", () => {
    render(
      <WorkspacePage
        initialWorkspaces={[
          { id: "1", name: "전사 문서", kind: "company", expires_at: null },
          { id: "2", name: "나의 문서", kind: "personal", expires_at: null },
          {
            id: "3",
            name: "임시 분석",
            kind: "temporary",
            expires_at: "2026-08-30T00:00:00Z",
          },
        ]}
      />,
    );

    expect(screen.getByText("전사 문서")).toBeVisible();
    expect(screen.getByText("나의 문서")).toBeVisible();
    expect(screen.getByText("임시 분석")).toBeVisible();
    expect(screen.queryByRole("option", { name: "팀" })).not.toBeInTheDocument();
  });
});
