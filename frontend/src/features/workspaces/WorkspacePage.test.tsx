import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, vi } from "vitest";

import { WorkspacePage } from "./WorkspacePage";

afterEach(() => vi.unstubAllGlobals());

describe("WorkspacePage", () => {
  it("groups real workspace kinds and keeps the creation form collapsed by default", async () => {
    const user = userEvent.setup();
    render(
      <WorkspacePage
        initialWorkspaces={[
          { id: "company-1", name: "제품 자료", kind: "company", expires_at: null },
          { id: "personal-1", name: "내 메모", kind: "personal", expires_at: null },
        ]}
      />,
    );

    expect(screen.getByRole("heading", { name: "파일함", level: 1 })).toBeVisible();
    expect(screen.getByRole("heading", { name: "회사 공간" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "개인 공간" })).toBeVisible();
    expect(screen.queryByRole("form", { name: "새 지식 공간 만들기" })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "공간 만들기" }));
    expect(screen.getByRole("form", { name: "새 지식 공간 만들기" })).toBeVisible();
  });

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
    expect(screen.getByRole("link", { name: /전사 문서/ })).toHaveAttribute(
      "href",
      "/workshop/workspaces/1/documents",
    );
    expect(screen.queryByRole("option", { name: "팀" })).not.toBeInTheDocument();
  });
});

it("filters authorized spaces by category and searches only workspace names", async () => {
  const user = userEvent.setup();
  render(<WorkspacePage initialWorkspaces={[
    { id: "company", name: "제품 자료", kind: "company", expires_at: null },
    { id: "team", name: "설계 팀", kind: "team", expires_at: null },
    { id: "personal", name: "My Notes", kind: "personal", expires_at: null },
  ]} />);
  expect(screen.getByRole("button", { name: "전체 공간 3" })).toHaveAttribute("aria-pressed", "true");
  await user.click(screen.getByRole("button", { name: "회사 공간 2" }));
  expect(screen.getByRole("link", { name: /설계 팀/ })).toBeVisible();
  expect(screen.queryByRole("link", { name: /My Notes/ })).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "전체 공간 3" }));
  const search = screen.getByRole("searchbox", { name: "공간 이름 검색" });
  await user.type(search, "  my notes  ");
  expect(screen.getByRole("link", { name: /My Notes/ })).toHaveAttribute("href", "/workshop/workspaces/personal/documents");
  expect(screen.queryByRole("link", { name: /제품 자료/ })).not.toBeInTheDocument();
  await user.clear(search);
  await user.type(search, "지속 보관");
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByText("검색한 이름과 일치하는 공간이 없습니다.")).toBeVisible();
  await user.clear(search);
  await user.click(screen.getByRole("button", { name: "임시 공간 0" }));
  expect(screen.getByText("접근 가능한 임시 공간이 없습니다.")).toBeVisible();
});

it("explains the empty file cabinet without inventing documents or counts", () => {
  render(<WorkspacePage />);
  expect(screen.getByRole("button", { name: "전체 공간 0" })).toBeVisible();
  expect(screen.getByText("접근 가능한 공간이 없습니다. 공간을 만들어 자료를 보관해 보세요.")).toBeVisible();
});

it("creates only on explicit submit and appends the actual response while blocking pending duplicates", async () => {
  let resolve!: (response: Response) => void;
  const fetcher = vi.fn<typeof fetch>(() => new Promise((settle) => { resolve = settle; }));
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<WorkspacePage />);
  await user.click(screen.getByRole("button", { name: "공간 만들기" }));
  await user.type(screen.getByRole("textbox", { name: "공간 이름" }), "  Draft name  ");
  await user.selectOptions(screen.getByRole("combobox", { name: "새 공간 유형" }), "personal");
  expect(fetcher).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "공간 만들기" }));
  expect(screen.getByRole("button", { name: "생성 중…" })).toBeDisabled();
  expect(screen.getByRole("textbox", { name: "공간 이름" })).toBeDisabled();
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  fireEvent.submit(screen.getByRole("form", { name: "새 지식 공간 만들기" }));
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(fetcher.mock.calls[0][0]).toBe("/api/v1/workspaces");
  expect(fetcher.mock.calls[0][1]?.method).toBe("POST");
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toEqual({ name: "Draft name", kind: "personal", expires_at: null });
  await act(async () => resolve(Response.json({ id: "server-space", name: "Server canonical name", kind: "personal", expires_at: null }, { status: 201 })));
  expect(screen.getByRole("link", { name: /Server canonical name/ })).toHaveAttribute("href", "/workshop/workspaces/server-space/documents");
  expect(screen.getByRole("status")).toHaveTextContent("생성했습니다");
  await user.type(screen.getByRole("textbox", { name: "공간 이름" }), "Next draft");
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
});

it.each([
  [403, "workspace_forbidden", "권한"],
  [409, "personal_workspace_exists", "개인 공간이 이미"],
  [422, "invalid_workspace", "이름과 유형, 만료"],
  [500, "internal_error", "완료하지 못했습니다"],
])("retains the failed draft and safely distinguishes HTTP %s", async (status, code, notice) => {
  vi.stubGlobal("fetch", vi.fn<typeof fetch>(async () => Response.json({ error: { code, message: "private server detail", correlation_id: "synthetic" } }, { status })));
  const user = userEvent.setup();
  render(<WorkspacePage />);
  await user.click(screen.getByRole("button", { name: "공간 만들기" }));
  await user.type(screen.getByRole("textbox", { name: "공간 이름" }), "Retained draft");
  await user.selectOptions(screen.getByRole("combobox", { name: "새 공간 유형" }), "personal");
  await user.click(screen.getByRole("button", { name: "공간 만들기" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(notice);
  expect(screen.queryByText("private server detail")).not.toBeInTheDocument();
  expect(screen.getByRole("textbox", { name: "공간 이름" })).toHaveValue("Retained draft");
  expect(screen.getByRole("combobox", { name: "새 공간 유형" })).toHaveValue("personal");
  expect(screen.queryByRole("link")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "공간 만들기" })).toBeEnabled();
});

it("requires a future temporary expiry and sends timezone-aware expiry only for temporary spaces", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json({ id: "temporary-id", name: "Temporary", kind: "temporary", expires_at: "2099-01-01T00:00:00Z" }, { status: 201 }));
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<WorkspacePage />);
  await user.click(screen.getByRole("button", { name: "공간 만들기" }));
  await user.type(screen.getByRole("textbox", { name: "공간 이름" }), "Temporary");
  const form = screen.getByRole("form", { name: "새 지식 공간 만들기" });
  fireEvent.submit(form);
  expect(screen.getByRole("alert")).toHaveTextContent("미래");
  fireEvent.change(screen.getByLabelText("만료 일시"), { target: { value: "2000-01-01T12:00" } });
  fireEvent.submit(form);
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.change(screen.getByLabelText("만료 일시"), { target: { value: "2099-01-01T12:00" } });
  await user.click(screen.getByRole("button", { name: "공간 만들기" }));
  expect(await screen.findByRole("link", { name: /Temporary/ })).toBeVisible();
  const payload = JSON.parse(fetcher.mock.calls[0][1]!.body as string);
  expect(payload.kind).toBe("temporary");
  expect(payload.expires_at).toBe(new Date("2099-01-01T12:00").toISOString());
});

it("rejects whitespace names and clears temporary expiry from non-temporary requests", async () => {
  const fetcher = vi.fn<typeof fetch>(async () => Response.json({ id: "personal-id", name: "Personal", kind: "personal", expires_at: null }, { status: 201 }));
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<WorkspacePage />);
  await user.click(screen.getByRole("button", { name: "공간 만들기" }));
  await user.type(screen.getByRole("textbox", { name: "공간 이름" }), "   ");
  fireEvent.change(screen.getByLabelText("만료 일시"), { target: { value: "2099-01-01T12:00" } });
  fireEvent.submit(screen.getByRole("form", { name: "새 지식 공간 만들기" }));
  expect(screen.getByRole("alert")).toHaveTextContent("이름");
  expect(fetcher).not.toHaveBeenCalled();
  await user.type(screen.getByRole("textbox", { name: "공간 이름" }), "Personal");
  await user.selectOptions(screen.getByRole("combobox", { name: "새 공간 유형" }), "personal");
  expect(screen.queryByLabelText("만료 일시")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "공간 만들기" }));
  expect(await screen.findByRole("link", { name: /Personal/ })).toBeVisible();
  expect(JSON.parse(fetcher.mock.calls[0][1]!.body as string)).toEqual({ name: "Personal", kind: "personal", expires_at: null });
});

it("rejects a name exceeding the server limit without sending a create request", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const user = userEvent.setup();
  render(<WorkspacePage />);
  await user.click(screen.getByRole("button", { name: "공간 만들기" }));
  fireEvent.change(screen.getByRole("textbox", { name: "공간 이름" }), { target: { value: "x".repeat(181) } });
  fireEvent.submit(screen.getByRole("form", { name: "새 지식 공간 만들기" }));
  expect(screen.getByRole("alert")).toHaveTextContent("180");
  expect(fetcher).not.toHaveBeenCalled();
});
