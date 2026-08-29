import { render, screen } from "@testing-library/react";

import { DocumentBrowser } from "./DocumentBrowser";

describe("DocumentBrowser", () => {
  it("shows document versions without premature search actions", () => {
    render(
      <DocumentBrowser
        workspaceName="나의 문서"
        initialDocuments={[
          {
            id: "document-1",
            name: "quarterly-report.pdf",
            latest_version: 2,
            status: "stored",
            job_id: "job-1",
          },
        ]}
      />,
    );

    expect(screen.getByText("quarterly-report.pdf")).toBeVisible();
    expect(screen.getByText("버전 2")).toBeVisible();
    expect(screen.queryByRole("button", { name: "검색" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "문서 올리기" })).toBeVisible();
    expect(screen.getByRole("button", { name: "상태 새로고침" })).toBeVisible();
  });
});
