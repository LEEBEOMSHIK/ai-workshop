import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgentCharacter } from "./AgentCharacter";
import { listPublicLabs } from "./catalog";

function rectangle(left: number, top: number, width: number, height: number): DOMRect {
  return {
    left,
    top,
    right: left + width,
    bottom: top + height,
    width,
    height,
    x: left,
    y: top,
    toJSON: () => ({}),
  } as DOMRect;
}

function mockMeasuredDialog(
  getAnchorRect: () => DOMRect,
  dialogRect = rectangle(0, 0, 320, 240),
) {
  return vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    return this.getAttribute("role") === "dialog" ? dialogRect : getAnchorRect();
  });
}

function runAnimationFramesImmediately() {
  let frameId = 0;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    frameId += 1;
    return frameId;
  });
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
}

describe("AgentCharacter", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    document.body.style.overflow = "";
  });

  it("renders an open dialog outside the animated character article", async () => {
    const user = userEvent.setup();
    const lab = listPublicLabs()[0];
    expect(lab).toBeDefined();

    render(<AgentCharacter lab={lab!} variant="roaming" />);

    await user.click(screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }));

    const dialog = screen.getByRole("dialog", { name: "RAG 총괄 소개" });

    expect(dialog.closest("article")).toBeNull();
    expect(dialog.parentElement?.parentElement).toBe(document.body);
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

  it("locks body scrolling while open and restores the exact previous value when closed", async () => {
    const user = userEvent.setup();
    const lab = listPublicLabs()[0];
    expect(lab).toBeDefined();
    document.body.style.overflow = "clip";

    render(<AgentCharacter lab={lab!} variant="working" />);

    await user.click(screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }));
    expect(document.body.style.overflow).toBe("hidden");

    await user.click(screen.getByRole("button", { name: "소개 닫기" }));
    expect(document.body.style.overflow).toBe("clip");
  });

  it("exposes a measured right placement through pixel CSS custom properties", async () => {
    const user = userEvent.setup();
    const lab = listPublicLabs()[0];
    expect(lab).toBeDefined();
    let anchorRect = rectangle(100, 200, 160, 260);
    mockMeasuredDialog(() => anchorRect);
    runAnimationFramesImmediately();

    render(<AgentCharacter lab={lab!} variant="working" />);

    await user.click(screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }));

    const dialog = screen.getByRole("dialog", { name: "RAG 총괄 소개" });
    expect(dialog).toHaveAttribute("data-placement", "right");
    expect(dialog.style.getPropertyValue("--dialog-left")).toBe("284px");
    expect(dialog.style.getPropertyValue("--dialog-top")).toBe("210px");
    expect(dialog.style.getPropertyValue("--dialog-tail-offset")).toBe("120px");

    anchorRect = rectangle(300, 250, 160, 200);
    act(() => window.dispatchEvent(new Event("resize")));

    expect(dialog.style.getPropertyValue("--dialog-left")).toBe("484px");
    expect(dialog.style.getPropertyValue("--dialog-top")).toBe("230px");
  });

  it("recomputes placement for orientation changes and capture-phase scrolls", async () => {
    const user = userEvent.setup();
    const lab = listPublicLabs()[0];
    expect(lab).toBeDefined();
    let anchorRect = rectangle(100, 200, 160, 260);
    mockMeasuredDialog(() => anchorRect);
    runAnimationFramesImmediately();

    render(<AgentCharacter lab={lab!} variant="roaming" />);
    await user.click(screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }));
    const dialog = screen.getByRole("dialog", { name: "RAG 총괄 소개" });

    anchorRect = rectangle(350, 300, 160, 200);
    act(() => window.dispatchEvent(new Event("orientationchange")));
    expect(dialog.style.getPropertyValue("--dialog-left")).toBe("534px");
    expect(dialog.style.getPropertyValue("--dialog-top")).toBe("280px");

    anchorRect = rectangle(200, 350, 160, 200);
    act(() => document.dispatchEvent(new Event("scroll", { bubbles: true })));
    expect(dialog.style.getPropertyValue("--dialog-left")).toBe("384px");
    expect(dialog.style.getPropertyValue("--dialog-top")).toBe("330px");
  });

  it("cancels its queued frame and removes viewport listeners when unmounted", async () => {
    const user = userEvent.setup();
    const lab = listPublicLabs()[0];
    expect(lab).toBeDefined();
    mockMeasuredDialog(() => rectangle(100, 200, 160, 260));
    const callbacks = new Map<number, FrameRequestCallback>();
    const cancelAnimationFrame = vi.fn();
    let frameId = 0;
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      frameId += 1;
      callbacks.set(frameId, callback);
      return frameId;
    });
    vi.stubGlobal("cancelAnimationFrame", cancelAnimationFrame);
    const removeEventListener = vi.spyOn(window, "removeEventListener");

    const { unmount } = render(<AgentCharacter lab={lab!} variant="working" />);
    await user.click(screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" }));

    unmount();

    expect(cancelAnimationFrame).toHaveBeenCalledWith(1);
    expect(removeEventListener).toHaveBeenCalledWith("resize", expect.any(Function));
    expect(removeEventListener).toHaveBeenCalledWith("orientationchange", expect.any(Function));
    expect(removeEventListener).toHaveBeenCalledWith("scroll", expect.any(Function), true);
  });

  it("closes with Escape and restores focus to the trigger", async () => {
    const user = userEvent.setup();
    const lab = listPublicLabs()[0];
    expect(lab).toBeDefined();

    render(<AgentCharacter lab={lab!} variant="roaming" />);

    const trigger = screen.getByRole("button", { name: "RAG 총괄에게 말 걸기" });
    await user.click(trigger);
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });
});
