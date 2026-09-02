import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AgentCharacter } from "./AgentCharacter";
import { listPublicLabs } from "./catalog";

describe("AgentCharacter", () => {
  it("focuses the close button and returns focus to the character trigger", async () => {
    const user = userEvent.setup();
    const lab = listPublicLabs()[0];
    expect(lab).toBeDefined();

    render(<AgentCharacter lab={lab!} variant="working" />);

    const trigger = screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "RAG 총괄 소개" });
    const closeButton = within(dialog).getByRole("button", { name: "소개 닫기" });
    expect(closeButton).toHaveFocus();

    await user.click(closeButton);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
