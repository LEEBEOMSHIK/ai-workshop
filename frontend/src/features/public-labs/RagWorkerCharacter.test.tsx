import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { listRagLabAgents } from "./rag-lab-agents";
import { RagWorkerCharacter } from "./RagWorkerCharacter";

describe("RagWorkerCharacter", () => {
  it("explains the selected worker's current task, input/output and handoff", async () => {
    const user = userEvent.setup();
    const agent = listRagLabAgents()[0];
    expect(agent).toBeDefined();

    render(<RagWorkerCharacter agent={agent!} />);
    await user.click(
      screen.getByRole("button", { name: "구조 분석가 루미에게 말 걸기" }),
    );

    const dialog = screen.getByRole("dialog", { name: "구조 분석가 루미 소개" });
    expect(within(dialog).getByText(agent!.intro)).toBeVisible();
    expect(within(dialog).getByText(agent!.currentWork)).toBeVisible();
    expect(within(dialog).getByText(agent!.inputOutput)).toBeVisible();
    expect(within(dialog).getByText(agent!.handoff)).toBeVisible();
    expect(within(dialog).queryByRole("link")).not.toBeInTheDocument();
  });

  it("focuses close and restores focus to the worker after closing", async () => {
    const user = userEvent.setup();
    const agent = listRagLabAgents()[0];
    expect(agent).toBeDefined();

    render(<RagWorkerCharacter agent={agent!} />);
    const trigger = screen.getByRole("button", {
      name: "구조 분석가 루미에게 말 걸기",
    });
    await user.click(trigger);

    const dialog = screen.getByRole("dialog", { name: "구조 분석가 루미 소개" });
    const closeButton = within(dialog).getByRole("button", { name: "소개 닫기" });
    expect(closeButton).toHaveFocus();

    await user.click(closeButton);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it("closes with Escape and restores the previous body overflow", async () => {
    const user = userEvent.setup();
    const agent = listRagLabAgents()[0];
    expect(agent).toBeDefined();
    document.body.style.overflow = "clip";

    render(<RagWorkerCharacter agent={agent!} />);
    const trigger = screen.getByRole("button", {
      name: "구조 분석가 루미에게 말 걸기",
    });
    await user.click(trigger);
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
    expect(document.body.style.overflow).toBe("clip");

    document.body.style.overflow = "";
  });
});
