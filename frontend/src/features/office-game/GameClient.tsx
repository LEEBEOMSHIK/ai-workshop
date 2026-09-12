"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { routes } from "../../shared/routing/routes";
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
  return <main className={styles.shell}>
    <header className={styles.header}>
      <Link href={routes.home} className={styles.brand}><span className={styles.logo} aria-hidden="true">A</span><span>AI WORKSHOP<small>RESEARCH CAMPUS</small></span></Link>
      <nav aria-label="공개 전시실" className="tw:flex tw:items-center tw:gap-6">
        <Link href={routes.labs}>AI Labs <span aria-hidden="true">↗</span></Link>
        <Link href={routes.workshopHome} className={styles.workshopLink}>내 작업소</Link>
      </nav>
    </header>
    <section className={styles.world} aria-label="게임형 AI 연구소">
      <div ref={host} className={styles.canvasHost} />
      <OfficeOverlay store={store} focusGame={focusGame} />
    </section>
  </main>;
}
