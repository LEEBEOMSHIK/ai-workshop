import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { headers } from "next/headers";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { ApplicationShell } from "../../../../features/navigation/ApplicationShell";
import { requireWorkspaceUser } from "../../../../shared/auth/server-session";
import WorkspaceLayout from "../layout";
import GalleryRoute from "./page";

const path = "/workshop/design-system";
vi.mock("next/navigation", () => ({ usePathname: () => "/workshop/design-system" }));
vi.mock("next/headers", () => ({ headers: vi.fn() }));
vi.mock("../../../../shared/auth/server-session", () => ({ requireWorkspaceUser: vi.fn() }));

beforeEach(() => {
  vi.mocked(headers).mockResolvedValue(new Headers({"x-ai-workshop-return-to": path}) as Awaited<ReturnType<typeof headers>>);
  vi.mocked(requireWorkspaceUser).mockResolvedValue({id: "member", role: "member", display_name: "Member", email: "member@example.test"});
});
afterEach(() => { cleanup(); vi.resetAllMocks(); vi.unstubAllGlobals(); });

async function protectedGallery() {
  return WorkspaceLayout({children: await GalleryRoute()});
}

it("exposes the gallery through the current member menu and omits it from public navigation", async () => {
  const workspace = render(await protectedGallery());
  expect(requireWorkspaceUser).toHaveBeenCalledWith(path);
  const nav = within(screen.getByRole("navigation", {name: "비공개 작업소"}));
  const link = nav.getByRole("link", {name: "디자인 시스템"});
  expect(link).toHaveAttribute("href", path);
  expect(link).toHaveAttribute("aria-current", "page");
  expect(screen.getByRole("heading", {level: 1, name: "디자인 시스템"})).toBeVisible();
  expect(screen.getByRole("heading", {name: "색상 팔레트"})).toBeVisible();
  workspace.unmount();
  render(<ApplicationShell area="public" />);
  expect(screen.queryByRole("link", {name: "디자인 시스템"})).not.toBeInTheDocument();
});

it("does not render the private gallery when workspace authentication redirects", async () => {
  vi.mocked(requireWorkspaceUser).mockRejectedValue(new Error("NEXT_REDIRECT"));
  await expect(protectedGallery()).rejects.toThrow("NEXT_REDIRECT");
  expect(screen.queryByRole("heading", {name: "디자인 시스템"})).not.toBeInTheDocument();
});

it("shows each reusable component with a named preview and its own expandable usage code", async () => {
  const user = userEvent.setup();
  render(await protectedGallery());
  expect(screen.getByRole("heading", {level: 2, name: "공통 컴포넌트"})).toBeVisible();

  for (const name of ["Button", "ButtonLink", "ChoiceGroup", "TextField", "SelectField", "TextAreaField",
    "StatusBadge", "Notice", "EmptyState", "Disclosure", "Pagination"]) {
    const card = within(screen.getByRole("article", {name}));
    expect(card.getByRole("heading", {name, level: 3})).toBeVisible();
    const summary = card.getByText("사용 코드", {selector: "summary"});
    const details = summary.closest("details");
    expect(details).not.toHaveAttribute("open");
    await user.click(summary);
    expect(details).toHaveAttribute("open");
    const code = details?.querySelector("code");
    expect(code).toBeVisible();
    expect(code).toHaveTextContent(name);
    await user.click(summary);
  }
});

it("supports local form edits, keyboard selection, disclosure and page navigation", async () => {
  const user = userEvent.setup();
  const fetch = vi.fn(() => Promise.reject(new Error("Unexpected preview network request")));
  vi.stubGlobal("fetch", fetch);
  render(await protectedGallery());
  const card = (name: string) => within(screen.getByRole("article", {name}));

  const buttons = card("Button");
  expect(buttons.getByRole("button", {name: "비활성"})).toBeDisabled();
  buttons.getByRole("button", {name: "저장"}).focus();
  await user.keyboard("{Enter}");
  expect(buttons.getByRole("status")).toHaveTextContent("저장");
  for (const [name, label] of [["TextField", "공간 이름"], ["TextAreaField", "본문"]]) {
    const field = card(name).getByRole("textbox", {name: label});
    await user.type(field, "합성 기록");
    expect(field).toHaveValue("합성 기록");
  }
  const select = card("SelectField").getByRole("combobox", {name: "공간 유형"});
  expect(select).toHaveValue("");
  await user.selectOptions(select, "personal");
  await user.selectOptions(select, "company");
  expect(select).toHaveDisplayValue("회사 공간");
  expect(within(select).getByRole("option", { name: "개인 공간", selected: false })).toBeInTheDocument();

  const choices = card("ChoiceGroup");
  const checked = choices.getByRole("radio", {checked: true});
  checked.focus();
  await user.keyboard("{ArrowRight}");
  expect(choices.getByRole("radio", {checked: true})).not.toBe(checked);

  const disclosure = card("Disclosure").getByText("처리 정보", {selector: "summary"});
  await user.click(disclosure);
  expect(disclosure.closest("details")).toHaveAttribute("open");

  const pager = card("Pagination");
  const previous = pager.getByRole("button", {name: /이전/});
  const next = pager.getByRole("button", {name: /다음/});
  expect(previous).toBeDisabled();
  next.focus();
  await user.keyboard("{Enter}");
  expect(pager.getByRole("navigation", {name: "예시 페이지"})).toHaveTextContent("2 / 3");
  expect(previous).toBeEnabled();
  await user.click(previous);
  expect(previous).toBeDisabled();
  expect(fetch).not.toHaveBeenCalled();
});
