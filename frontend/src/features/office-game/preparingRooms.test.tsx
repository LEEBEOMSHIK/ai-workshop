import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { createGameStore } from "./gameStore";
import { OfficeOverlay } from "./OfficeOverlay";
import { officeMap, readOfficeObjects } from "./map";
import { roomAt } from "./spatial";

afterEach(cleanup);
const cases = [["finetuning", "파인튜닝 연구소", 288], ["study", "AI 공부실", 768], ["ontology", "온톨로지 연구소", 1248]] as const;

it("connects all three preparing rooms to spawn with foot-sized paths and notice points", () => {
  const world = readOfficeObjects(officeMap);
  for (const [id, , x] of cases) {
    expect(roomAt({ x, y: 1740 }, world.rooms)?.id).toBe(id);
    expect(world.notices.find((notice) => notice.id === id)).toMatchObject({ x, y: 1820 });
    const path = [world.spawn, { x: 768, y: 1380 }, { x, y: 1380 }, { x, y: 1740 }];
    for (let i = 1; i < path.length; i++) for (let t = 0; t <= 1; t += .01) {
      const px = path[i - 1].x + (path[i].x - path[i - 1].x) * t;
      const py = path[i - 1].y + (path[i].y - path[i - 1].y) * t;
      expect(world.collisions.some((s) => px + 11 > s.x && px - 11 < s.x + s.width && py > s.y && py - 16 < s.y + s.height), `${id}: ${px},${py}`).toBe(false);
    }
    expect(world.npcs.some((npc) => roomAt(npc, world.rooms)?.id === id)).toBe(false);
  }
});

it("guards notice selection by readiness and identity and keeps it separate from NPC selection", () => {
  const store = createGameStore();
  store.getState().selectNotice("study");
  expect(store.getState().dialogueOpen).toBe(false);
  store.getState().setStatus("ready");
  store.getState().selectNotice("unknown");
  expect(store.getState().dialogueOpen).toBe(false);
  store.getState().setNearbyNotice("study");
  store.getState().openDialogue();
  expect(store.getState()).toMatchObject({ selectedNotice: "study", selectedNPC: null, dialogueOpen: true });
  store.getState().selectNpc("founder");
  store.getState().selectNotice("ontology");
  expect(store.getState().selectedNotice).toBe("study");
  store.getState().closeDialogue();
  expect(store.getState().selectedNotice).toBeNull();
  store.getState().setNearbyNotice("unknown");
  expect(store.getState().interactionAvailable).toBe(false);
  store.getState().setStatus("error");
  store.getState().selectNotice("ontology");
  expect(store.getState().dialogueOpen).toBe(false);
});

it.each(cases)("shows %s notice purpose and recruitment status without service actions", (id, title) => {
  const store = createGameStore(); store.getState().setStatus("ready");
  const canvas = document.createElement("canvas"); canvas.tabIndex = 0; document.body.append(canvas);
  render(<OfficeOverlay store={store} focusGame={() => canvas.focus()} />);
  act(() => store.getState().setNearbyNotice(id));
  fireEvent.click(screen.getByRole("button", { name: new RegExp(`${title}.*안내`) }));
  const dialog = screen.getByRole("dialog", { name: title });
  expect(dialog).toHaveTextContent("관리자 모집 중 · 기능 준비 중");
  expect(dialog.querySelectorAll("a")).toHaveLength(0);
  expect(dialog.querySelectorAll("button")).toHaveLength(1);
  const close = screen.getByRole("button", { name: "대화 닫기" });
  expect(close).toHaveFocus();
  fireEvent.keyDown(close, { key: "Tab", shiftKey: true }); expect(close).toHaveFocus();
  fireEvent.keyDown(close, { key: "Escape" });
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(canvas).toHaveFocus();
  act(() => store.getState().selectNotice(id));
  fireEvent.click(screen.getByRole("button", { name: "대화 닫기" }));
  expect(store.getState().dialogueOpen).toBe(false); canvas.remove();
});
