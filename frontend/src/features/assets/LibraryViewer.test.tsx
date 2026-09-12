import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import type { DocumentSummary } from "./api";
import { LibraryViewer } from "./LibraryViewer";

const document: DocumentSummary = {
  active_version_id: "version-2",
  folder_id: "folder-1",
  id: "document-1",
  job_id: null,
  latest_version: 3,
  latest_version_id: "version-3",
  name: "예시 문서.md",
  status: "processing",
  workspace_id: "workspace-1",
};

function withEvidenceAware(fetcher: (path: string, input: RequestInfo | URL) => Promise<Response>): void {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.includes("/evidence-approval-requests")) {
      return Response.json({ items: [], next_cursor: null, context: null });
    }
    return fetcher(path, input);
  }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("resets an in-flight approval submission when selecting another version", async () => {
  let resolveSubmission!: (response: Response) => void;
  const submission = new Promise<Response>((resolve) => { resolveSubmission = resolve; });
  const fetcher = vi.fn<typeof fetch>(async (input, init) => {
    const path = String(input);
    if (path.includes("/evidence-approval-requests")) {
      if (init?.method === "POST") return submission;
      return Response.json({ items: [], next_cursor: null, context: {
        revision_id: path.includes("version-1") ? "version-1" : "version-2",
        provider: "development_codex_exec", approval_status: "unapproved", approval_generation: 0,
      } });
    }
    if (path.includes("/library/")) return Response.json({ items: [
      { id: "version-2", number: 2, media_type: "text/plain", size: 20, status: "ready" },
      { id: "version-1", number: 1, media_type: "text/plain", size: 10, status: "ready" },
    ], next_cursor: null });
    return Response.json({ kind: "text", text: "본문", version: 1, name: "예시.txt", size: 10 });
  });
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<LibraryViewer document={document} initialVersionId={null} onClose={vi.fn()} onVersionChange={vi.fn()} />);
  const requestButton = await screen.findByRole("button", { name: "이 버전에 대한 Codex 승인 요청" });
  await waitFor(() => expect(requestButton).toBeEnabled());
  await user.click(requestButton);
  await user.click(screen.getByRole("button", { name: /버전 1/ }));
  await waitFor(() => expect(screen.getByRole("button", { name: "이 버전에 대한 Codex 승인 요청" })).toBeEnabled());
  const readsBeforeCompletion = fetcher.mock.calls.filter(([, init]) => init?.method !== "POST").length;
  await act(async () => resolveSubmission(Response.json({ id: "old-request" })));
  expect(screen.queryByText(/요청이 접수되었습니다/)).not.toBeInTheDocument();
  expect(fetcher.mock.calls.filter(([, init]) => init?.method !== "POST")).toHaveLength(readsBeforeCompletion);
});

it("hides previous approval context while the selected version is loading", async () => {
  let resolveApproval!: (response: Response) => void;
  const approval = new Promise<Response>((resolve) => { resolveApproval = resolve; });
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.includes("/evidence-approval-requests")) {
      if (path.includes("version-1")) return approval;
      return Response.json({ items: [], next_cursor: null, context: {
        revision_id: "version-2", provider: "development_codex_exec", approval_status: "approved", approval_generation: 3,
      } });
    }
    if (path.includes("/library/")) return Response.json({ items: [
      { id: "version-1", number: 1, media_type: "text/plain", size: 10, status: "ready" },
    ], next_cursor: null });
    return Response.json({ kind: "text", text: "본문", version: 1, name: "예시.txt", size: 10 });
  }));
  render(<LibraryViewer document={document} initialVersionId={null} onClose={vi.fn()} onVersionChange={vi.fn()} />);
  await screen.findByText(/이 버전은 현재 승인 상태/);
  await userEvent.setup().click(screen.getByRole("button", { name: /버전 1/ }));
  expect(screen.queryByText(/이 버전은 현재 승인 상태/)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "이 버전에 대한 Codex 승인 요청" })).toBeDisabled();
  await act(async () => resolveApproval(Response.json({ items: [], next_cursor: null, context: null })));
  expect(screen.getByRole("button", { name: "이 버전에 대한 Codex 승인 요청" })).toBeEnabled();
});

it("opens the exact active READY version and exposes version state", async () => {
  withEvidenceAware(async (path) => {
    if (path.includes("/library/documents/document-1/versions")) {
      return Response.json({
        items: [
          { id: "version-3", number: 3, media_type: "text/markdown", size: 25, status: "processing" },
          { id: "version-2", number: 2, media_type: "text/markdown", size: 24, status: "ready" },
        ],
        next_cursor: null,
      });
    }
    if (path.endsWith("/preview")) {
      return Response.json({
        asset_version_id: "version-2",
        document_id: "document-1",
        kind: "markdown",
        name: "예시 문서.md",
        page_count: null,
        size: 24,
        text: "# 예시 텍스트\n<img src=x>",
        version: 2,
      });
    }
    return Response.json({ status: 404, message: "unhandled" } as never, { status: 404 });
  });

  render(<LibraryViewer document={document} initialVersionId={null} onClose={vi.fn()} onVersionChange={vi.fn()} />);

  expect(await screen.findByText("# 예시 텍스트", { exact: false })).toBeVisible();
  expect(screen.getByRole("button", { name: /버전 2/ })).toHaveAttribute("aria-pressed", "true");
  expect(screen.getByRole("button", { name: /버전 3/ })).toBeVisible();
  const information = screen.getByRole("region", { name: "문서 정보" });
  expect(within(information).getByText("예시 문서.md")).toBeVisible();
  expect(within(information).getByText("24 B")).toBeVisible();
  expect(within(information).getByText("Markdown")).toBeVisible();
});

it("closes on Escape so its owner can restore focus", async () => {
  withEvidenceAware(async (path) => {
    if (path.includes("/library/")) {
      return Response.json({ items: [], next_cursor: null });
    }
    return Response.json({
      asset_version_id: "version-2",
      document_id: "document-1",
      kind: "text",
      name: "예시 문서.md",
      page_count: null,
      size: 1,
      text: "문서 본문",
      version: 2,
    });
  });

  const close = vi.fn();
  const user = userEvent.setup();
  render(<LibraryViewer document={document} initialVersionId="version-2" onClose={close} onVersionChange={vi.fn()} />);
  await screen.findByText("문서 본문");

  await user.keyboard("{Escape}");

  expect(close).toHaveBeenCalledTimes(1);
});

it("shows unsupported format guidance and exposes only the download action", async () => {
  withEvidenceAware(async (path) => {
    if (path.includes("/library/")) {
      return Response.json({
        items: [{
          id: "version-2",
          number: 2,
          media_type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          size: 40,
          status: "ready",
        }],
        next_cursor: null,
      });
    }
    if (path.endsWith("/preview")) {
      return Response.json({
        asset_version_id: "version-2",
        document_id: "document-1",
        kind: "unsupported",
        name: "예시 문서.docx",
        page_count: null,
        size: 40,
        text: null,
        version: 2,
      });
    }
    return Response.json({ status: 404, message: "unhandled" } as never, { status: 404 });
  });

  render(
    <LibraryViewer
      document={{ ...document, name: "예시 문서.docx", latest_version: 2, latest_version_id: "version-2", status: "ready" }}
      initialVersionId={null}
      onClose={vi.fn()}
      onVersionChange={vi.fn()}
    />,
  );

  expect(await screen.findByText("이 형식은 아직 미리보기를 지원하지 않습니다.")).toBeVisible();
  expect(screen.getByRole("link", { name: "원본 내려받기" })).toHaveAttribute(
    "href",
    "/api/v1/documents/document-1/versions/version-2/content",
  );
  const information = screen.getByRole("region", { name: "문서 정보" });
  expect(within(information).getByText("예시 문서.docx")).toBeVisible();
});

it("keeps honest document info when selected version is not in loaded metadata", async () => {
  withEvidenceAware(async (path) => {
    if (path.includes("/library/")) {
      return Response.json({
        items: [{ id: "version-3", number: 3, media_type: "text/markdown", size: 30, status: "processing" }],
        next_cursor: "more",
      });
    }
    if (path.endsWith("/preview")) {
      return Response.json({
        asset_version_id: "version-old",
        document_id: "document-1",
        kind: "text",
        name: "기록.txt",
        page_count: null,
        size: 12,
        text: "이전 본문",
        version: 1,
      });
    }
    return Response.json({ status: 404, message: "unhandled" } as never, { status: 404 });
  });

  render(<LibraryViewer document={document} initialVersionId="version-old" onClose={vi.fn()} onVersionChange={vi.fn()} />);

  expect(await screen.findByText("이전 본문")).toBeVisible();
  const information = screen.getByRole("region", { name: "문서 정보" });
  expect(within(information).getByText("기록.txt")).toBeVisible();
  expect(within(information).getByText("12 B")).toBeVisible();
  expect(within(information).getByText("상세 형식 정보 없음")).toBeVisible();
  expect(within(information).getByText("원본 준비됨")).toBeVisible();
});

it("shows honest empty-state when there is no previewable original", async () => {
  withEvidenceAware(async () => Response.json({ items: [], next_cursor: null }));

  render(
    <LibraryViewer
      document={{ ...document, active_version_id: null }}
      initialVersionId={null}
      onClose={vi.fn()}
      onVersionChange={vi.fn()}
    />,
  );

  expect(await screen.findByText("열람할 수 있는 활성 원본 버전이 없습니다.")).toBeVisible();
  expect(screen.getByRole("button", { name: "이 버전에 대한 Codex 승인 요청" })).toBeDisabled();
  expect(screen.queryByText("승인 요청 상태를 불러오는 중…")).not.toBeInTheDocument();
  expect(screen.queryByText(/아래에서 Codex 자료 검토 요청/)).not.toBeInTheDocument();
  expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).includes("/evidence-approval-requests"))).toBe(false);
  const information = screen.getByRole("region", { name: "문서 정보" });
  expect(within(information).getByText("예시 문서.md")).toBeVisible();
});

it("releases PDF page object URLs when page changes and closes", async () => {
  const createObjectURL = vi.fn(() => "blob:synthetic-page");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

  withEvidenceAware(async (path) => {
    if (path.includes("/library/")) {
      return Response.json({
        items: [{ id: "version-2", number: 2, media_type: "application/pdf", size: 40, status: "ready" }],
        next_cursor: null,
      });
    }
    if (path.endsWith("/preview")) {
      return Response.json({
        asset_version_id: "version-2",
        document_id: "document-1",
        kind: "pdf",
        name: "예시.pdf",
        page_count: 2,
        size: 40,
        text: null,
        version: 2,
      });
    }
    if (path.includes("/pdf/pages/")) {
      return new Response(new Blob(["png"], { type: "image/png" }));
    }
    return Response.json({ status: 404, message: "unhandled" } as never, { status: 404 });
  });

  const user = userEvent.setup();
  const view = render(
    <LibraryViewer
      document={{ ...document, name: "예시.pdf", latest_version: 2, latest_version_id: "version-2", status: "ready" }}
      initialVersionId={null}
      onClose={vi.fn()}
      onVersionChange={vi.fn()}
    />,
  );

  expect(await screen.findByRole("img", { name: /1쪽/ })).toBeVisible();
  await user.click(screen.getByRole("button", { name: /다음 페이지/ }));
  await waitFor(() => expect(revokeObjectURL).toHaveBeenCalledWith("blob:synthetic-page"));
  await act(async () => view.unmount());
  expect(revokeObjectURL).toHaveBeenCalledTimes(2);
});

it("appends the next bounded version page", async () => {
  const fetcher = vi.fn<(input: RequestInfo | URL) => Promise<Response>>(async (input) => {
    const path = String(input);
    if (path.endsWith("?cursor=next-versions")) {
      return Response.json({
        items: [{ id: "version-1", number: 1, media_type: "text/markdown", size: 10, status: "ready" }],
        next_cursor: null,
      });
    }
    if (path.includes("/library/")) {
      return Response.json({
        items: [{ id: "version-2", number: 2, media_type: "text/markdown", size: 20, status: "ready" }],
        next_cursor: "next-versions",
      });
    }
    if (path.endsWith("/preview")) {
      return Response.json({
        asset_version_id: "version-2",
        document_id: "document-1",
        kind: "text",
        name: "예시 문서.md",
        page_count: null,
        size: 20,
        text: "본문",
        version: 2,
      });
    }
    return Response.json({ status: 404, message: "unhandled" } as never, { status: 404 });
  });
  withEvidenceAware(async (path) => fetcher(path));

  const user = userEvent.setup();
  render(<LibraryViewer document={{ ...document, latest_version: 2, latest_version_id: "version-2", status: "ready" }} initialVersionId={null} onClose={vi.fn()} onVersionChange={vi.fn()} />);

  await user.click(await screen.findByRole("button", { name: /버전 더 보기/ }));
  expect(await screen.findByRole("button", { name: /버전 1/ })).toBeVisible();
  expect(screen.queryByRole("button", { name: /버전 더 보기/ })).not.toBeInTheDocument();
  expect(fetcher).toHaveBeenCalledTimes(3);
});

it("uses cursor once during repeated activation", async () => {
  let resolveVersions!: (response: Response) => void;
  const nextVersions = new Promise<Response>((resolve) => {
    resolveVersions = resolve;
  });
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.endsWith("?cursor=next-versions")) return nextVersions;
    if (path.includes("/library/")) {
      return Promise.resolve(
        Response.json({
          items: [{ id: "version-2", number: 2, media_type: "text/plain", size: 20, status: "ready" }],
          next_cursor: "next-versions",
        }),
      );
    }
    if (path.endsWith("/preview")) {
      return Promise.resolve(
        Response.json({
          asset_version_id: "version-2",
          document_id: "document-1",
          kind: "text",
          name: "예시 문서.txt",
          page_count: null,
          size: 20,
          text: "본문",
          version: 2,
        }),
      );
    }
    return Response.json({ status: 404, message: "unhandled" } as never, { status: 404 });
  });
  withEvidenceAware(async (path) => fetcher(path));

  const user = userEvent.setup();
  render(<LibraryViewer document={{ ...document, latest_version: 2, latest_version_id: "version-2", status: "ready" }} initialVersionId={null} onClose={vi.fn()} onVersionChange={vi.fn()} />);

  const loadMore = await screen.findByRole("button", { name: /버전 더 보기/ });
  await user.click(loadMore);
  expect(loadMore).toBeDisabled();
  await user.click(loadMore);
  expect(fetcher.mock.calls.filter(([input]) => String(input).endsWith("?cursor=next-versions"))).toHaveLength(1);

  await act(async () => resolveVersions(
    Response.json({
      items: [{ id: "version-1", number: 1, media_type: "text/plain", size: 10, status: "ready" }],
      next_cursor: null,
    }),
  ));

  expect(await screen.findAllByRole("button", { name: /버전 1/ })).toHaveLength(1);
});

it("keeps preview visible when only version list fails", async () => {
  withEvidenceAware(async (path) => {
    if (path.includes("/library/")) {
      return Response.json({
        error: { code: "synthetic_failure", message: "private", correlation_id: "synthetic" },
      }, { status: 500 });
    }
    return Response.json({
      asset_version_id: "version-2",
      document_id: "document-1",
      kind: "text",
      name: "예시 문서.md",
      page_count: null,
      size: 20,
      text: "문서 본문",
      version: 2,
    });
  });

  render(<LibraryViewer document={{ ...document, latest_version: 2, latest_version_id: "version-2", status: "ready" }} initialVersionId={null} onClose={vi.fn()} onVersionChange={vi.fn()} />);

  expect(await screen.findByText("문서 본문")).toBeVisible();
  expect(screen.getByText("버전 목록을 불러오지 못했습니다.")).toBeVisible();
  expect(screen.getByRole("button", { name: "버전 목록 다시 시도" })).toBeVisible();
});

it("retries a failed PDF page and does not reload original preview", async () => {
  const createObjectURL = vi.fn(() => "blob:retry-page");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });

  let pageAttempts = 0;
  const fetcher = vi.fn<typeof fetch>(async (input) => {
    const path = String(input);
    if (path.includes("/library/")) {
      return Response.json({
        items: [{ id: "version-2", number: 2, media_type: "application/pdf", size: 40, status: "ready" }],
        next_cursor: null,
      });
    }
    if (path.endsWith("/preview")) {
      return Response.json({
        asset_version_id: "version-2",
        document_id: "document-1",
        kind: "pdf",
        name: "예시.pdf",
        page_count: 1,
        size: 40,
        text: null,
        version: 2,
      });
    }
    if (path.includes("/pdf/pages/")) {
      pageAttempts += 1;
      return pageAttempts === 1
        ? Response.json({ error: { code: "render_failed", message: "private", correlation_id: "synthetic" } }, { status: 500 })
        : new Response(new Blob(["png"], { type: "image/png" }));
    }
    return Response.json({ items: [], next_cursor: null, context: null });
  });
  withEvidenceAware(async (path) => fetcher(path));

  render(<LibraryViewer document={{ ...document, name: "예시.pdf", latest_version: 2, latest_version_id: "version-2", status: "ready" }} initialVersionId={null} onClose={vi.fn()} onVersionChange={vi.fn()} />);

  await waitFor(() => expect(fetcher).toHaveBeenCalled());
  const retryButton = await screen.findByRole("button", { name: /페이지 다시 시도/ });
  await userEvent.setup().click(retryButton);

  expect(await screen.findByRole("img", { name: /1쪽/ })).toBeVisible();
  const pageCalls = fetcher.mock.calls.filter(([input]) => String(input).includes("/pdf/pages/")).length;
  expect(pageCalls).toBeGreaterThanOrEqual(2);
  expect(fetcher.mock.calls.filter(([input]) => String(input).endsWith("/preview"))).toHaveLength(1);
});
