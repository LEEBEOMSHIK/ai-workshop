import { fireEvent, render, screen } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { afterEach, vi } from "vitest";

import { routes } from "../../../app/router";
import type { HighlightSpan } from "./api";
import { SourceViewer } from "./SourceViewer";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("SourceViewer", () => {
  it("maps multiple non-overlapping original offsets without interpreting source text as HTML", async () => {
    let captured: [RequestInfo | URL, RequestInit | undefined] | undefined;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        captured = [input, init];
        return jsonResponse(normalizedText("text/plain"));
      }),
    );

    render(
      <SourceViewer
        assetVersionId="asset-version-1"
        projectionId="projection-1"
        highlights={[
          highlight("keyword", 0, 2, "환매"),
          highlight("semantic", 4, 6, "3일"),
          highlight("keyword", 999, 1005, "잘못된 범위"),
        ]}
      />,
    );

    expect(await screen.findByRole("heading", { name: "환매 규정.txt" })).toBeVisible();
    expect(screen.getByText("환매", { selector: "mark.keyword-highlight" })).toHaveAttribute(
      "aria-label",
      "정확·키워드 일치",
    );
    expect(screen.getByText("3일", { selector: "mark.semantic-highlight" })).toHaveAttribute(
      "aria-label",
      "의미 일치",
    );
    expect(screen.getByText(/<img src=x onerror=alert\(1\)>/)).toBeVisible();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("유효하지 않은 하이라이트 범위를 제외했습니다.")).toBeVisible();
    expect(captured).toEqual([
      "/api/v1/rag/sources/asset-version-1/normalized-text?projection_id=projection-1",
      { credentials: "include" },
    ]);
  });

  it("interprets text offsets as Python Unicode code points across astral characters", async () => {
    const text = "📈환매🚀3일";
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          ...normalizedText("text/plain"),
          elements: [
            {
              ...normalizedText("text/plain").elements[0],
              text,
              location: {
                ...normalizedText("text/plain").elements[0].location,
                char_end: Array.from(text).length,
              },
            },
          ],
        }),
      ),
    );

    render(
      <SourceViewer
        assetVersionId="asset-version-1"
        projectionId="projection-1"
        highlights={[
          highlight("keyword", 0, 1, "\ud83d"),
          highlight("keyword", 1, 3, "환매"),
          highlight("semantic", 3, 4, "🚀"),
          highlight("keyword", 4, 6, "3일"),
        ]}
      />,
    );

    const document = await screen.findByRole("region", { name: "정규화된 원문" });
    expect(document).toHaveTextContent(text);
    expect(screen.getByText("환매", { selector: "mark.keyword-highlight" })).toBeVisible();
    expect(screen.getByText("🚀", { selector: "mark.semantic-highlight" })).toBeVisible();
    expect(screen.getByText("3일", { selector: "mark.keyword-highlight" })).toBeVisible();
    expect(document.querySelectorAll("mark")).toHaveLength(3);
    expect(screen.getByText("유효하지 않은 하이라이트 범위를 제외했습니다.")).toBeVisible();
  });

  it("uses the authorized PDF image dimensions for overlays and labels missing coordinates", async () => {
    const createObjectURL = vi.fn(() => "blob:authorized-page");
    const revokeObjectURL = vi.fn();
    vi.stubGlobal("URL", {
      ...URL,
      createObjectURL,
      revokeObjectURL,
    });
    const requests: Array<[RequestInfo | URL, RequestInit | undefined]> = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        requests.push([input, init]);
        if (String(input).includes("normalized-text")) {
          return jsonResponse(normalizedText("application/pdf"));
        }
        return new Response(new Blob(["png"], { type: "image/png" }), {
          status: 200,
          headers: { "content-type": "image/png" },
        });
      }),
    );

    const { unmount } = render(
      <SourceViewer
        assetVersionId="asset-version-1"
        projectionId="projection-1"
        highlights={[
          { ...highlight("keyword", 0, 2, "환매"), page: 1, bbox: [60, 100, 180, 140] },
          { ...highlight("semantic", 4, 6, "3일"), page: 1, bbox: null },
        ]}
      />,
    );

    const pageImage = await screen.findByRole("img", { name: "환매 규정.txt 1페이지" });
    expect(
      screen.queryByText("정확·키워드 일치 원문 좌표를 사용할 수 없습니다."),
    ).not.toBeInTheDocument();
    Object.defineProperty(pageImage, "naturalWidth", { configurable: true, value: 600 });
    Object.defineProperty(pageImage, "naturalHeight", { configurable: true, value: 800 });
    fireEvent.load(pageImage);

    const overlay = screen.getByLabelText("정확·키워드 일치 강조 영역");
    expect(overlay).toHaveClass("keyword-highlight");
    expect(overlay).toHaveStyle({ left: "10%", top: "12.5%", width: "20%", height: "5%" });
    expect(screen.getByText("의미 일치 원문 좌표를 사용할 수 없습니다.")).toBeVisible();
    expect(requests[1]).toEqual([
      "/api/v1/rag/sources/asset-version-1/pdf/pages/1?projection_id=projection-1",
      { credentials: "include" },
    ]);
    expect(createObjectURL).toHaveBeenCalledOnce();

    unmount();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:authorized-page");
  });

  it.each([
    [404, "원문을 찾을 수 없습니다.", false],
    [503, "원문 파일을 일시적으로 불러올 수 없습니다.", true],
  ])("renders a non-disclosing %i viewer state", async (status, message, retryable) => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse(
          {
            error: {
              code: "private_detail",
              message: "권한 밖 문서 이름",
              correlation_id: "correlation-1",
            },
          },
          status,
        ),
      ),
    );

    render(
      <SourceViewer
        assetVersionId="asset-version-1"
        projectionId="projection-1"
        highlights={[]}
      />,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.queryByText(/권한 밖 문서 이름/)).not.toBeInTheDocument();
    const retryButton = screen.queryByRole("button", { name: "다시 시도" });
    if (retryable) expect(retryButton).toBeInTheDocument();
    else expect(retryButton).not.toBeInTheDocument();
  });

  it("registers the source route without accepting a caller object key", async () => {
    let requestedUrl = "";
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        requestedUrl = String(input);
        return jsonResponse(normalizedText("text/plain"));
      }),
    );
    const router = createMemoryRouter(routes, {
      initialEntries: ["/rag/sources/asset-version-1?projectionId=projection-1&objectKey=forbidden"],
    });

    render(<RouterProvider router={router} />);

    expect(await screen.findByRole("heading", { name: "환매 규정.txt" })).toBeVisible();
    expect(requestedUrl).toBe(
      "/api/v1/rag/sources/asset-version-1/normalized-text?projection_id=projection-1",
    );
    expect(requestedUrl).not.toContain("objectKey");
  });
});

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function normalizedText(mediaType: string) {
  const text = "환매는 3일 전에 신청합니다. <img src=x onerror=alert(1)>";
  return {
    document_id: "document-1",
    asset_version_id: "asset-version-1",
    asset_version_number: 4,
    workspace_id: "company-1",
    folder_id: null,
    projection_id: "projection-1",
    title: "환매 규정.txt",
    media_type: mediaType,
    parser_name: "test-parser",
    parser_version: "1",
    elements: [
      {
        id: "element-1",
        ordinal: 0,
        kind: "paragraph",
        text,
        section_path: ["환매"],
        location: {
          element_id: "element-1",
          page: mediaType === "application/pdf" ? 1 : null,
          char_start: 0,
          char_end: text.length,
          bbox: mediaType === "application/pdf" ? [0, 0, 600, 800] : null,
        },
        confidence: 1,
      },
    ],
  };
}

function highlight(
  kind: HighlightSpan["kind"],
  charStart: number,
  charEnd: number,
  text: string,
): HighlightSpan {
  return {
    kind,
    evidence_unit_id: "evidence-1",
    text,
    char_start: charStart,
    char_end: charEnd,
    page: null,
    bbox: null,
    score: kind === "semantic" ? 0.9 : null,
    warnings: [],
  };
}
