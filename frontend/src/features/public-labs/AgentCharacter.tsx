"use client";

import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";

import type { PublicLab } from "./catalog";
import styles from "./PublicLabScene.module.css";

interface AgentCharacterProps {
  lab: PublicLab;
  variant: "roaming" | "working";
}

export function AgentCharacter({ lab, variant }: AgentCharacterProps) {
  const [isOpen, setIsOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  function closeDialog() {
    setIsOpen(false);
    triggerRef.current?.focus();
  }

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    closeRef.current?.focus();

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
        triggerRef.current?.focus();
      }
    }

    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [isOpen]);

  return (
    <article className={`${styles.character} ${styles[variant]}`}>
      <button
        ref={triggerRef}
        className={styles.characterButton}
        type="button"
        aria-label={`${lab.manager.name}에게 말 걸기`}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        onClick={() => setIsOpen(true)}
      >
        <span className={styles.avatar} aria-hidden="true">
          <span className={styles.antenna} />
          <span className={styles.head}>
            <span className={styles.faceLight} />
            <span className={styles.faceLight} />
          </span>
          <span className={styles.body}>
            <span className={styles.statusLight} />
          </span>
          <span className={styles.tool} />
        </span>
        <span className={styles.identity}>
          <span className={styles.role}>{lab.manager.role}</span>
          <strong>{lab.manager.name}</strong>
          <span>{lab.statusLabel}</span>
        </span>
      </button>

      {isOpen ? (
        <div className={styles.dialogLayer}>
          <div
            className={styles.dialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby={titleId}
            aria-describedby={descriptionId}
          >
            <button
              ref={closeRef}
              className={styles.closeButton}
              type="button"
              aria-label="소개 닫기"
              onClick={closeDialog}
            >
              <span aria-hidden="true">×</span>
            </button>
            <p className={styles.dialogEyebrow}>{lab.eyebrow}</p>
            <h2 id={titleId}>{lab.manager.name} 소개</h2>
            <div id={descriptionId} className={styles.dialogCopy}>
              <p>{lab.manager.intro}</p>
              <p>{lab.manager.invitation}</p>
            </div>
            <Link className={styles.labLink} href={lab.href}>
              {lab.manager.ctaLabel}
            </Link>
          </div>
        </div>
      ) : null}
    </article>
  );
}
