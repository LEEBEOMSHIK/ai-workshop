import { fireEvent } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { createGameStore } from "./gameStore";
import { prepareInitialGameFocus } from "./initialFocus";
import { OfficeInput } from "./systems/OfficeInput";

const cleanups: (() => void)[] = [];
afterEach(() => {
  cleanups.splice(0).reverse().forEach((cleanup) => cleanup());
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

function setup() {
  vi.spyOn(document, "hasFocus").mockReturnValue(true);
  const host = document.createElement("div");
  const button = document.createElement("button");
  document.body.append(host, button);
  const store = createGameStore();
  const dispose = prepareInitialGameFocus(host, store);
  cleanups.push(dispose);
  const canvas = document.createElement("canvas");
  canvas.tabIndex = 0;
  host.append(canvas);
  return { host, button, store, canvas, dispose };
}

describe("initial game focus", () => {
  it("allows immediate WASD when the asynchronously created canvas becomes ready", () => {
    const { store, canvas } = setup();
    const input = new OfficeInput(canvas, () => undefined);
    cleanups.push(() => input.destroy());
    expect(document.activeElement).not.toBe(canvas);
    store.getState().setStatus("ready");
    expect(canvas).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "w" });
    expect(input.direction()).toEqual({ x: 0, y: -1 });
  });

  it.each(["focus", "pointer", "tab"])("respects a %s choice during loading even if focus later returns to body", (choice) => {
    const { store, button, canvas } = setup();
    if (choice === "focus") { button.focus(); button.blur(); }
    if (choice === "pointer") fireEvent.pointerDown(button);
    if (choice === "tab") fireEvent.keyDown(document.body, { key: "Tab" });
    store.getState().setStatus("ready");
    expect(canvas).not.toHaveFocus();
  });

  it.each(["hidden", "blur", "dialogue"])("never steals focus after %s interrupts loading", (interruption) => {
    const { store, canvas } = setup();
    if (interruption === "hidden") {
      const visibility = vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
      fireEvent(document, new Event("visibilitychange"));
      visibility.mockReturnValue("visible");
    }
    if (interruption === "blur") fireEvent.blur(window);
    if (interruption === "dialogue") store.setState({ dialogueOpen: true });
    store.getState().setStatus("ready");
    store.getState().closeDialogue();
    fireEvent.focus(window);
    expect(canvas).not.toHaveFocus();
  });

  it("does not refocus after ready, updates or tab return and leaves navigation keys alone", () => {
    const { store, button, canvas } = setup();
    const input = new OfficeInput(canvas, () => undefined);
    cleanups.push(() => input.destroy());
    store.getState().setStatus("ready");
    fireEvent.keyDown(canvas, { key: "w" });
    button.focus();
    expect(input.direction()).toEqual({ x: 0, y: 0 });
    fireEvent.keyDown(button, { key: "w" });
    expect(input.direction()).toEqual({ x: 0, y: 0 });
    fireEvent.blur(window);
    fireEvent.focus(window);
    store.getState().updateWorld({ x: 10, y: 20 }, "lobby");
    expect(button).toHaveFocus();
  });

  it("cleans up an abandoned mount and permits its fresh StrictMode replacement", () => {
    const { host, store, canvas, dispose } = setup();
    dispose();
    store.getState().setStatus("ready");
    expect(canvas).not.toHaveFocus();
    store.getState().setStatus("loading");
    cleanups.push(prepareInitialGameFocus(host, store));
    store.getState().setStatus("ready");
    expect(canvas).toHaveFocus();
  });
});
