import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";

import { routes } from "../../shared/routing/routes";
import { LoginPage } from "./LoginPage";
import { LoginLayout } from "./LoginLayout";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
  usePathname: () => "/login",
}));

beforeEach(() => replace.mockClear());

describe("LoginPage", () => {
  it("keeps only the standalone brand header for server errors", async () => {
    render(<LoginLayout><main role="alert">서버 오류</main></LoginLayout>);
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI Workshop 홈" })).toHaveAttribute("href", routes.home);
    expect(screen.getByRole("alert")).toHaveTextContent("서버 오류");
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
  });
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
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI Workshop 홈" })).toBeVisible();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
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
    expect(screen.queryByRole("navigation", { name: "공개 전시실" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "AI Workshop 홈" })).toHaveAttribute("href", routes.home);
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();

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
