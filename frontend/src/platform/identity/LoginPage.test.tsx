import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LoginPage } from "./LoginPage";

describe("LoginPage", () => {
  it("shows the authenticated owner after a successful login", async () => {
    const user = userEvent.setup();
    render(
      <LoginPage
        authenticate={async () => ({
          id: "6806a6c1-04c4-4f2c-87d8-8cd1bf06e898",
          display_name: "LEE BEOMSHIK",
          email: "bumcity135@naver.com",
          role: "owner",
        })}
      />,
    );

    await user.type(screen.getByLabelText("이메일"), "bumcity135@naver.com");
    await user.type(screen.getByLabelText("비밀번호"), "correct-password");
    await user.click(screen.getByRole("button", { name: "작업소 입장" }));

    expect(await screen.findByText("LEE BEOMSHIK님, 환영합니다.")).toBeVisible();
  });
});
