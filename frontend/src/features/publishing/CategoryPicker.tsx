"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import { catalogPath } from "./catalog-query";
import { publicTopicLabel } from "./topic-registry";
import type { PublicStudyCatalog } from "./types";
import styles from "./Publishing.module.css";

export function CategoryPicker({ topics, selectedTopic }: {
  topics: PublicStudyCatalog["topics"];
  selectedTopic?: string;
}) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const panelId = useId();
  const titleId = useId();
  const searchId = useId();
  const selected = topics.find(({ key }) => key === selectedTopic);
  const currentLabel = selectedTopic
    ? `${publicTopicLabel(selectedTopic)}${selected ? ` (${selected.count})` : ""}`
    : "전체";
  const normalizedSearch = search.trim().toLocaleLowerCase();
  const matches = topics.filter(({ key }) => `${publicTopicLabel(key)} ${key}`.toLocaleLowerCase().includes(normalizedSearch));

  useEffect(() => {
    if (!open) return;
    const trigger = triggerRef.current;
    searchRef.current?.focus();
    const dismissOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setOpen(false);
      }
    };
    const dismissOutside = (event: PointerEvent) => {
      if (event.target instanceof Node && !panelRef.current?.contains(event.target) && !trigger?.contains(event.target)) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", dismissOnEscape);
    document.addEventListener("pointerdown", dismissOutside);
    return () => {
      document.removeEventListener("keydown", dismissOnEscape);
      document.removeEventListener("pointerdown", dismissOutside);
      trigger?.focus();
    };
  }, [open]);

  function toggle() {
    setSearch("");
    setOpen(!open);
  }

  return (
    <div className={styles.categoryPicker}>
      <button ref={triggerRef} type="button" className={styles.categoryTrigger} aria-label={`카테고리: ${currentLabel}`} aria-haspopup="dialog" aria-expanded={open} aria-controls={open ? panelId : undefined} onClick={toggle}>
        <span>카테고리: {currentLabel}</span>
        <svg className={styles.categoryChevron} width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" focusable="false">
          <path d="m4 6 4 4 4-4" />
        </svg>
      </button>
      {open && <div ref={panelRef} id={panelId} role="dialog" aria-labelledby={titleId} className={styles.categoryPanel}>
        <div className={styles.categoryPanelHeader}>
          <h2 id={titleId}>카테고리 선택</h2>
          <button type="button" aria-label="카테고리 선택 닫기" onClick={() => setOpen(false)}>닫기</button>
        </div>
        <label htmlFor={searchId}>카테고리 검색</label>
        <div className={styles.categorySearch}>
          <input ref={searchRef} id={searchId} type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="이름 또는 키로 검색" />
          {search && <button type="button" onClick={() => { setSearch(""); searchRef.current?.focus(); }}>검색어 지우기</button>}
        </div>
        <Link className={styles.categoryOption} href={catalogPath({ page: 1 })} prefetch={false} aria-current={!selectedTopic ? "true" : undefined} onClick={() => setOpen(false)}>전체</Link>
        <ul className={styles.categoryOptions} aria-label="연구 기록 카테고리">
          {matches.map(({ key, count }) => <li key={key}>
            <Link className={styles.categoryOption} href={catalogPath({ page: 1, topic: key })} prefetch={false} aria-current={selectedTopic === key ? "true" : undefined} onClick={() => setOpen(false)}>{publicTopicLabel(key)} ({count})</Link>
          </li>)}
        </ul>
        {matches.length === 0 && <p className={styles.muted} role="status">검색 결과가 없습니다.</p>}
      </div>}
    </div>
  );
}
