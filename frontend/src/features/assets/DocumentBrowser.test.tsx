import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

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

  it("uploads a new version only from the selected document row", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      expect(input).toBe("/api/v1/documents/document-1/versions");
      expect(init?.method).toBe("POST");
      return new Response(
        JSON.stringify({
          id: "document-1",
          name: "quarterly-report.pdf",
          latest_version: 3,
          status: "stored",
          job_id: null,
        }),
        { status: 201, headers: { "content-type": "application/json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();

    render(
      <DocumentBrowser
        workspaceId="workspace-1"
        workspaceName="나의 문서"
        initialDocuments={[
          {
            id: "document-1",
            name: "quarterly-report.pdf",
            latest_version: 2,
            status: "ready",
            job_id: null,
          },
        ]}
      />,
    );

    await user.upload(
      screen.getByLabelText("quarterly-report.pdf 새 버전 파일"),
      new File(["updated"], "quarterly-report.pdf", { type: "application/pdf" }),
    );

    expect(await screen.findByText("버전 3")).toBeVisible();
    expect(screen.queryByText("버전 2")).not.toBeInTheDocument();
    expect(screen.getAllByText("quarterly-report.pdf")).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("explains an exact-content duplicate without exposing server detail", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(
          JSON.stringify({
            error: {
              code: "duplicate_document_content",
              message: "Internal duplicate detail",
              correlation_id: "correlation-1",
            },
          }),
          { status: 409, headers: { "content-type": "application/json" } },
        ),
      ),
    );
    const user = userEvent.setup();
    render(<DocumentBrowser workspaceId="workspace-1" workspaceName="나의 문서" />);

    await user.upload(
      screen.getByLabelText("새 문서 파일"),
      new File(["duplicate"], "renamed-copy.pdf", { type: "application/pdf" }),
    );

    expect(await screen.findByRole("status")).toHaveTextContent(
      "같은 내용의 문서가 이 지식 공간에 이미 있습니다.",
    );
    expect(screen.queryByText("Internal duplicate detail")).not.toBeInTheDocument();
  });
});
