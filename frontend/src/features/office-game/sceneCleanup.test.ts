import { EventEmitter } from "node:events";
import { expect, it } from "vitest";
import { onSceneExit } from "./sceneCleanup";

it("releases scene-owned resources on destroy without requiring shutdown", () => {
  const events = new EventEmitter();
  let released = 0;
  onSceneExit(events, () => { released++; });
  events.emit("destroy");
  expect(released).toBe(1);
  expect(events.listenerCount("shutdown")).toBe(0);
  events.emit("shutdown");
  expect(released).toBe(1);
});
it("releases only once if shutdown precedes destroy", () => {
  const events = new EventEmitter();
  let released = 0;
  onSceneExit(events, () => { released++; });
  events.emit("shutdown"); events.emit("destroy");
  expect(released).toBe(1);
  expect(events.listenerCount("destroy")).toBe(0);
});
