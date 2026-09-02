import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { routes } from "../../shared/routing/routes";
import { HomePage } from "./HomePage";

describe("public AI Workshop landing", () => {
  it("introduces the public workshop through its Lab manager", async () => {
    const user = userEvent.setup();
    render(<HomePage />);

    expect(
      screen.getByRole("heading", { name: "AI 기술 관리자들이 일하는 작업소" }),
    ).toBeVisible();
    expect(
      screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }),
    ).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }));

    const dialog = screen.getByRole("dialog", { name: "RAG 총괄 소개" });
    expect(dialog).toHaveTextContent("문서 검색과 근거 기반 답변 기술");
    expect(
      within(dialog).getByRole("link", { name: "RAG 연구실 들어가기" }),
    ).toHaveAttribute("href", routes.ragLab);

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
