import { act, fireEvent, render, screen, cleanup } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { createGameStore } from "./gameStore";
import { OfficeOverlay } from "./OfficeOverlay";
import { OfficeInput } from "./systems/OfficeInput";

afterEach(cleanup);
describe("React dialogue bridge", () => {
  it("collapses the first-visit guide without hiding its restore control", () => {
    const store = createGameStore();
    render(<OfficeOverlay store={store} focusGame={() => undefined} />);

    expect(screen.getByRole("heading", { name: "연구소에 오신 것을환영합니다." })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "이동 안내 접기" }));

    expect(screen.queryByRole("heading", { name: "연구소에 오신 것을환영합니다." })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "이동 안내 펼치기" })).toBeVisible();
    expect(document.getElementById("office-guide-content")).toHaveAttribute("hidden");
  });

  it("shows a nearby NPC prompt, opens a dialog and closes with Escape", () => {
    const store = createGameStore();
    store.getState().setStatus("ready");
    let restored = false;
    render(<OfficeOverlay store={store} focusGame={() => { restored = true; }} />);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    act(() => store.getState().setNearbyNpc("rag-chief"));
    fireEvent.click(screen.getByRole("button", { name: /RAG 총괄 · 대화/ }));
    expect(screen.getByRole("dialog")).toHaveAccessibleName("RAG 총괄");
    expect(screen.getByRole("link", { name: /RAG 연구소 들어가기/ })).toHaveAttribute("href", "/labs/rag");
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(store.getState().dialogueOpen).toBe(false);
    expect(restored).toBe(true);
  });
  it("shows Founder research directions, traps focus and restores canvas focus on close", () => {
    const store = createGameStore();
    store.getState().setStatus("ready");
    const canvas = document.createElement("canvas"); canvas.tabIndex = 0; document.body.append(canvas);
    render(<OfficeOverlay store={store} focusGame={() => canvas.focus()} />);
    act(() => store.getState().setNearbyNpc("founder"));
    fireEvent.click(screen.getByRole("button", { name: /LEE BEOMSHIK · 대화/ }));
    expect(screen.getByRole("dialog")).toHaveAccessibleName("LEE BEOMSHIK");
    expect(screen.getByRole("dialog")).toHaveTextContent("Founder");
    expect(screen.getByRole("list", { name: "공개 연구 방향" }).children).toHaveLength(3);
    const close = screen.getByRole("button", { name: "대화 닫기" });
    expect(close).toHaveFocus();
    fireEvent.keyDown(close, { key: "Tab" });
    expect(close).toHaveFocus();
    fireEvent.click(close);
    expect(canvas).toHaveFocus();
    canvas.remove();
  });
});

describe("focused game input", () => {
  it("captures only canvas keys, clears on blur and suppresses held interaction repeat", () => {
    const canvas = document.createElement("canvas"); canvas.tabIndex = 0; document.body.append(canvas);
    let interactions = 0;
    const input = new OfficeInput(canvas, () => { interactions++; });
    fireEvent.keyDown(window, { key: "w" });
    expect(input.direction()).toEqual({ x: 0, y: 0 });
    canvas.focus();
    fireEvent.keyDown(canvas, { key: "w" });
    expect(input.direction()).toEqual({ x: 0, y: -1 });
    fireEvent.keyDown(canvas, { key: "e" });
    fireEvent.keyDown(canvas, { key: "e", repeat: true });
    expect(interactions).toBe(1);
    fireEvent.blur(canvas);
    expect(input.direction()).toEqual({ x: 0, y: 0 });
    input.destroy();
    fireEvent.keyDown(canvas, { key: "e" });
    expect(interactions).toBe(1);
    canvas.remove();
  });
});
