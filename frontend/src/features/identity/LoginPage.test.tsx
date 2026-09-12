import { act, render, screen } from "@testing-library/react";
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
  it("announces a failed login after exposing the pending state", async () => {
    let rejectLogin!: (reason: Error) => void;
    const pending = new Promise<never>((_resolve, reject) => { rejectLogin = reject; });
    const user = userEvent.setup();
    render(<LoginPage authenticate={() => pending} />);

    await user.type(screen.getByLabelText("이메일"), "owner@example.test");
    await user.type(screen.getByLabelText("비밀번호"), "incorrect-password");
    await user.click(screen.getByRole("button", { name: "작업소 입장" }));
    expect(screen.getByRole("button", { name: "확인 중…" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "확인 중…" }).closest("form")).toHaveAttribute("aria-busy", "true");

    await act(async () => rejectLogin(new Error("invalid_credentials")));
    expect(screen.getByRole("alert")).toHaveTextContent("이메일 또는 비밀번호를 확인해 주세요.");
    expect(screen.getByRole("button", { name: "작업소 입장" })).toBeEnabled();
    expect(replace).not.toHaveBeenCalled();
  });

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
          display_name: "TEST OWNER",
          email: "owner@example.test",
          role: "owner",
        })}
      />,
    );

    expect(
      screen.getByRole("link", { name: "로그인 없이 AI Lab 둘러보기" }),
    ).toHaveAttribute("href", routes.labs);
    expect(screen.getByRole("navigation", { name: "공개 전시실" })).toBeInTheDocument();

    await user.type(screen.getByLabelText("이메일"), "owner@example.test");
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
