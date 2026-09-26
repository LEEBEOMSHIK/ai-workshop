"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { PublicNavigation } from "../navigation/PublicNavigation";
import { createGameStore } from "./gameStore";
import { mountGame } from "./lifecycle";
import { prepareInitialGameFocus } from "./initialFocus";
import { OfficeOverlay } from "./OfficeOverlay";
import styles from "./Office.module.css";

export function GameClient() {
  const host = useRef<HTMLDivElement>(null);
  const [store] = useState(createGameStore);
  useEffect(() => {
    const parent = host.current;
    if (!parent) return;
    const stopInitialFocus = prepareInitialGameFocus(parent, store);
    const unmountGame = mountGame(async () => {
      const { createPhaserGame } = await import("./PhaserGame");
      return () => createPhaserGame(parent, store);
    }, () => store.getState().setStatus("error"));
    return () => { stopInitialFocus(); unmountGame(); };
  }, [store]);
  const focusGame = () => host.current?.querySelector("canvas")?.focus({ preventScroll: true });
  const handleMenuOpenChange = useCallback((open: boolean) => {
    // Movement is canvas-scoped; blur clears held keys and the native modal
    // keeps the canvas inert. Closing the menu does not steal focus back.
    if (open) host.current?.querySelector("canvas")?.blur();
  }, []);
  return <PublicNavigation immersive onMenuOpenChange={handleMenuOpenChange}>
    <main className={styles.shell}>
    <section className={styles.world} aria-label="게임형 AI 연구소">
      <div ref={host} className={styles.canvasHost} />
      <OfficeOverlay store={store} focusGame={focusGame} />
    </section>
    </main>
  </PublicNavigation>;
}
