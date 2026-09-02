import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";

import { LoginPage } from "./LoginPage";

describe("LoginPage", () => {
  it("returns to the requested protected page after a successful login", async () => {
    const user = userEvent.setup();
    const router = createMemoryRouter(
      [
        {
          path: "/login",
          element: (
            <LoginPage
              authenticate={async () => ({
                id: "6806a6c1-04c4-4f2c-87d8-8cd1bf06e898",
                display_name: "LEE BEOMSHIK",
                email: "bumcity135@naver.com",
                role: "owner",
              })}
            />
          ),
        },
        { path: "/rag/search", element: <h1>근거 검색 작업소</h1> },
      ],
      { initialEntries: ["/login?next=%2Frag%2Fsearch"] },
    );
    render(<RouterProvider router={router} />);

    await user.type(screen.getByLabelText("이메일"), "bumcity135@naver.com");
    await user.type(screen.getByLabelText("비밀번호"), "correct-password");
    await user.click(screen.getByRole("button", { name: "작업소 입장" }));

    expect(await screen.findByRole("heading", { name: "근거 검색 작업소" })).toBeVisible();
  });
});
