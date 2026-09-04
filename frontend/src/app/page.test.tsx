import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { routes } from "../shared/routing/routes";
import HomeRoute, { metadata } from "./page";

describe("HomeRoute", () => {
  it("introduces the public Lab entrance before the working Lab floor", async () => {
    const user = userEvent.setup();
    render(<HomeRoute />);

    expect(
      screen.getByRole("heading", { name: "AI 기술 관리자들을 만나는 연구소 입구" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }),
    ).toBeVisible();
    expect(
      screen.getByRole("link", { name: "연구실 전체 보기" }),
    ).toHaveAttribute("href", routes.labs);
    expect(screen.queryByText("문서 수집 라인")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }));

    expect(
      screen.getByRole("link", { name: "RAG 연구실 들어가기" }),
    ).toHaveAttribute("href", routes.ragLab);
  });

  it("declares the public entrance as the canonical route", () => {
    expect(metadata.alternates?.canonical).toBe("/");
  });
});
