import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, vi } from "vitest";

import { routes } from "../../shared/routing/routes";
import { SetupPage } from "./SetupPage";

const replace = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace }),
}));

beforeEach(() => replace.mockClear());

describe("SetupPage", () => {
  it("creates the first administrator and opens the workspace", async () => {
    const user = userEvent.setup();
    const requests: Array<Record<string, string>> = [];
    render(
      <SetupPage
        createOwner={async (request) => {
          requests.push(request);
          return {
            id: "6806a6c1-04c4-4f2c-87d8-8cd1bf06e898",
            display_name: request.display_name,
            email: request.email,
            role: "owner",
          };
        }}
      />,
    );

    await user.type(screen.getByLabelText("이름"), "LEE BEOMSHIK");
    await user.type(screen.getByLabelText("이메일"), "bumcity135@naver.com");
    await user.type(screen.getByLabelText("비밀번호"), "correct-password");
    await user.type(screen.getByLabelText("비밀번호 확인"), "correct-password");
    await user.click(screen.getByRole("button", { name: "관리자 계정 만들기" }));

    expect(replace).toHaveBeenCalledWith(routes.workshopHome);
    expect(requests).toEqual([
      {
        display_name: "LEE BEOMSHIK",
        email: "bumcity135@naver.com",
        password: "correct-password",
        password_confirmation: "correct-password",
      },
    ]);
  });

  it("shows a local error when password confirmation does not match", async () => {
    const user = userEvent.setup();
    let called = false;
    render(
      <SetupPage
        createOwner={async () => {
          called = true;
          throw new Error("must not be called");
        }}
      />,
    );

    await user.type(screen.getByLabelText("이름"), "LEE BEOMSHIK");
    await user.type(screen.getByLabelText("이메일"), "bumcity135@naver.com");
    await user.type(screen.getByLabelText("비밀번호"), "correct-password");
    await user.type(screen.getByLabelText("비밀번호 확인"), "different-password");
    await user.click(screen.getByRole("button", { name: "관리자 계정 만들기" }));

    expect(screen.getByRole("alert")).toHaveTextContent("비밀번호가 일치하지 않습니다.");
    expect(called).toBe(false);
  });
});
