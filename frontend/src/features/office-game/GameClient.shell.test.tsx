import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { vi } from "vitest";
import { GameClient } from "./GameClient";
import { OfficeInput } from "./systems/OfficeInput";

const runtime = vi.hoisted(() => ({ mount: vi.fn(), stop: vi.fn() }));
vi.mock("./lifecycle", () => ({ mountGame: () => { runtime.mount(); return runtime.stop; } }));
vi.mock("../navigation/PublicNavigation", () => ({
  PublicNavigation: ({ children, immersive, onMenuOpenChange }: { children?: ReactNode; immersive?: boolean; onMenuOpenChange?: (open: boolean) => void }) => <div data-testid="public-shell" data-immersive={immersive}>
    <nav aria-label="Shared public menu"><button onClick={() => onMenuOpenChange?.(true)}>Open menu</button></nav>{children}
  </div>,
}));

it("fills one immersive public shell and stops held game input when its menu opens", () => {
  runtime.mount.mockClear(); runtime.stop.mockClear();
  const rendered = render(<GameClient />);
  expect(screen.getByTestId("public-shell")).toHaveAttribute("data-immersive", "true");
  expect(screen.getByRole("main")).not.toContainElement(screen.getByRole("navigation"));
  expect(screen.getAllByRole("main")).toHaveLength(1);
  const canvas = document.createElement("canvas");
  canvas.tabIndex = 0;
  screen.getByRole("region", { name: "게임형 AI 연구소" }).firstElementChild!.append(canvas);
  const controls = new OfficeInput(canvas, vi.fn());
  canvas.focus();
  fireEvent.keyDown(canvas, { key: "w" });
  expect(controls.direction().y).toBe(-1);
  fireEvent.click(screen.getByRole("button", { name: "Open menu" }));
  expect(controls.direction()).toEqual({ x: 0, y: 0 });
  expect(document.activeElement).not.toBe(canvas);
  controls.destroy();
  rendered.rerender(<GameClient />);
  expect(runtime.mount).toHaveBeenCalledTimes(1);
  rendered.unmount();
  expect(runtime.stop).toHaveBeenCalledTimes(1);
});
