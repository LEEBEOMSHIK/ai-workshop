import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";

import { routes } from "../../shared/routing/routes";
import { LoginPage } from "./LoginPage";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

beforeEach(() => replace.mockClear());

describe("LoginPage", () => {
  it("opens the workshop home when no protected return path was requested", async () => {
    const user = userEvent.setup();
    render(
      <LoginPage
        authenticate={async () => ({
          id: "6806a6c1-04c4-4f2c-87d8-8cd1bf06e898",
          display_name: "TEST OWNER",
          email: "owner@example.test",
          role: "owner",
        })}
      />,
    );

    await user.type(screen.getByLabelText("이메일"), "owner@example.test");
    await user.type(screen.getByLabelText("비밀번호"), "correct-password");
    await user.click(screen.getByRole("button", { name: "작업소 입장" }));

    expect(replace).toHaveBeenCalledWith(routes.workshopHome);
  });

  it("returns to the requested protected page after a successful login", async () => {
    const user = userEvent.setup();
    render(
      <LoginPage
        nextPath={routes.workshopRagSearch}
        authenticate={async () => ({
          id: "6806a6c1-04c4-4f2c-87d8-8cd1bf06e898",
          display_name: "LEE BEOMSHIK",
          email: "bumcity135@naver.com",
          role: "owner",
        })}
      />,
    );

    expect(
      screen.getByRole("link", { name: "로그인 없이 AI Lab 둘러보기" }),
    ).toHaveAttribute("href", routes.labs);
    expect(screen.getByRole("navigation", { name: "공개 전시실" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("이메일"), "bumcity135@naver.com");
    await user.type(screen.getByLabelText("비밀번호"), "correct-password");
    await user.click(screen.getByRole("button", { name: "작업소 입장" }));

    expect(replace).toHaveBeenCalledWith(routes.workshopRagSearch);
    expect(screen.getByRole("link", { name: "작업소 열기" })).toHaveAttribute(
      "href",
      routes.workshopRagSearch,
    );
    expect(screen.getByRole("link", { name: "AI Lab으로 돌아가기" })).toHaveAttribute(
      "href",
      routes.labs,
    );
  });
});
