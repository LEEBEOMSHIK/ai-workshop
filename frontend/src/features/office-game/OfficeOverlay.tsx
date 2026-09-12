"use client";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useStore } from "zustand";
import type { GameStore } from "./gameStore";
import { npcCatalog, rooms } from "./npcs";
import { preparingRooms, preparingStatus } from "./preparingRooms";
import styles from "./Office.module.css";

function Dialogue({ store, focusGame }: { store: GameStore; focusGame: () => void }) {
  const selected = useStore(store, (state) => state.selectedNPC);
  const npc = npcCatalog.find((entry) => entry.id === selected);
  const selectedNotice = useStore(store, (state) => state.selectedNotice);
  const notice = preparingRooms.find((entry) => entry.id === selectedNotice);
  const dialog = useRef<HTMLDivElement>(null);
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => { closeButton.current?.focus(); }, []);
  if (!npc && !notice) return null;
  const close = () => { store.getState().closeDialogue(); focusGame(); };
  return <div className={styles.backdrop}>
    <div ref={dialog} role="dialog" aria-modal="true" aria-labelledby="office-dialog-title" className={styles.dialog}
      onKeyDown={(event) => {
        if (event.key === "Escape") { event.preventDefault(); close(); }
        if (event.key === "Tab") {
          const elements = dialog.current?.querySelectorAll<HTMLElement>("a[href], button:not(:disabled)");
          const first = elements?.[0], last = elements?.[elements.length - 1];
          if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
          else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
        }
      }}>
      <div className="tw:flex tw:items-center tw:justify-between tw:gap-4">
        <span className={styles.eyebrow}>{npc?.eyebrow ?? "PREPARING / RECRUITMENT"}</span>
        <button ref={closeButton} className={styles.close} onClick={close} aria-label="대화 닫기">✕</button>
      </div>
      <h2 id="office-dialog-title">{npc?.name ?? notice?.name}</h2>
      {notice && <><span className={styles.role}>{preparingStatus}</span><p>{notice.purpose}</p><p className={styles.note}>공간을 둘러보며 준비 중인 연구 주제를 확인할 수 있습니다.</p></>}
      {npc && <>
      <span className={styles.role}>{npc.role}</span>
      <p>{npc.introduction}</p><p>{npc.invitation}</p>
      {npc.directions.length > 0 && <ol className={styles.directions} aria-label="공개 연구 방향">
        {npc.directions.map((direction) => <li key={direction.recipient}>
          <span>{direction.recipient}에게</span><h3>{direction.subject}</h3><p>{direction.message}</p>
        </li>)}
      </ol>}
      {npc.href && <Link href={npc.href} className={styles.primary}>{npc.linkLabel} <span aria-hidden="true">↗</span></Link>}
      <p className={styles.note}>공개 소개 연출입니다. 실제 지시 이력이나 실행 상태가 아니며, AI 작업을 실행하지 않습니다.</p>
      </>}
    </div>
  </div>;
}

export function OfficeOverlay({ store, focusGame }: { store: GameStore; focusGame: () => void }) {
  const [guideOpen, setGuideOpen] = useState(true);
  const room = useStore(store, (state) => state.currentRoom);
  const position = useStore(store, (state) => state.playerPosition);
  const nearby = useStore(store, (state) => state.nearbyNPC);
  const nearbyNotice = useStore(store, (state) => state.nearbyNotice);
  const open = useStore(store, (state) => state.dialogueOpen);
  const status = useStore(store, (state) => state.status);
  const npc = npcCatalog.find((entry) => entry.id === nearby);
  const notice = preparingRooms.find((entry) => entry.id === nearbyNotice);
  return <>
    <div className={styles.roomBadge} aria-live="polite"><span className={styles.dot} />{rooms[room as keyof typeof rooms] ?? room}<span className={styles.floor}>1F</span></div>
    <aside className={`${styles.guide} ${guideOpen ? "" : styles.guideCollapsed}`} aria-label="이동 안내">
      <button className={styles.guideToggle} type="button" aria-expanded={guideOpen} aria-controls="office-guide-content"
        aria-label={`이동 안내 ${guideOpen ? "접기" : "펼치기"}`} onClick={() => setGuideOpen((value) => !value)}>
        <span aria-hidden="true">{guideOpen ? "−" : "?"}</span>
      </button>
      <div id="office-guide-content" hidden={!guideOpen}>
        <span className={styles.eyebrow}>FIRST MISSION</span>
        <h1>연구소에 오신 것을<br />환영합니다.</h1>
        <p>위쪽 사장실의 <strong>Founder</strong>,<br />오른쪽 연구소의 <strong>RAG 총괄</strong>을<br />클릭하거나 가까이에서 E로 만나세요.</p>
        <p>아래쪽 복도에는 준비 중인 세 공간과<br />관리자 모집 안내판이 있어요.</p>
        <span className={styles.route}>FOUNDER <span aria-hidden="true">←</span> LOBBY <span aria-hidden="true">→</span> RAG</span>
      </div>
    </aside>
    <div className={styles.bottomBar}>
      <p><kbd>W A S D</kbd> / <kbd>방향키</kbd> 이동 <span className={styles.separator}>·</span> <kbd>E</kbd> 대화</p>
      <output aria-label="플레이어 위치" data-x={Math.round(position.x)} data-y={Math.round(position.y)} className={styles.coordinates}>{Math.round(position.x)} : {Math.round(position.y)}</output>
    </div>
    {status === "loading" && <div role="status" className={styles.message}>연구소를 준비하고 있어요…</div>}
    {status === "error" && <div role="alert" className={styles.message}>게임 화면을 불러오지 못했습니다. 새로고침하거나 상단의 AI Labs 메뉴를 이용해 주세요.</div>}
    {status === "ready" && !open && <div className={styles.interaction}>
      {npc ? <button className={styles.primary} onClick={() => store.getState().openDialogue()}><kbd>E</kbd> {npc.name} · 대화</button>
        : notice ? <button className={styles.primary} onClick={() => store.getState().openDialogue()}><kbd>E</kbd> {notice.name} · 안내</button>
        : <button className={styles.focusButton} onClick={focusGame}>이동 키가 반응하지 않으면 여기를 클릭</button>}
    </div>}
    {open && <Dialogue store={store} focusGame={focusGame} />}
  </>;
}
