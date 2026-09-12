import { render, screen } from "@testing-library/react";
import { vi } from "vitest";
import { GameClient } from "./GameClient";

// Canvas startup is unrelated to the navigation contract and requires WebGL.
vi.mock("./lifecycle", () => ({ mountGame: () => () => undefined }));

it("enters the protected workshop without forcing an already signed-in visitor through login", () => {
  render(<GameClient />);
  expect(screen.getByRole("link", { name: "내 작업소" })).toHaveAttribute("href", "/workshop/workspaces");
});
