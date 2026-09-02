import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AgentCharacter } from "./AgentCharacter";
import { listPublicLabs } from "./catalog";

describe("AgentCharacter", () => {
  it("renders an open dialog outside the animated character article", async () => {
    const user = userEvent.setup();
    const lab = listPublicLabs()[0];
    expect(lab).toBeDefined();

    render(<AgentCharacter lab={lab!} variant="roaming" />);

    await user.click(screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }));

    const dialog = screen.getByRole("dialog", { name: "RAG 총괄 소개" });

    expect(dialog.closest("article")).toBeNull();
  });

  it("cycles Tab and Shift+Tab focus within the open dialog", async () => {
    const user = userEvent.setup();
    const lab = listPublicLabs()[0];
    expect(lab).toBeDefined();

    render(<AgentCharacter lab={lab!} variant="roaming" />);

    await user.click(screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }));

    const dialog = screen.getByRole("dialog", { name: "RAG 총괄 소개" });
    const closeButton = within(dialog).getByRole("button", { name: "소개 닫기" });
    const labLink = within(dialog).getByRole("link", { name: "RAG 연구실 들어가기" });

    expect(closeButton).toHaveFocus();
    await user.tab();
    expect(labLink).toHaveFocus();
    await user.tab();
    expect(closeButton).toHaveFocus();
    await user.tab({ shift: true });
    expect(labLink).toHaveFocus();
  });

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
