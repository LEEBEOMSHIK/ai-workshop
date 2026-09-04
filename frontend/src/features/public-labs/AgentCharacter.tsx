"use client";

import Link from "next/link";
import {
  type CSSProperties,
  type KeyboardEvent as ReactKeyboardEvent,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { createPortal } from "react-dom";

import type { PublicLab } from "./catalog";
import {
  calculateDialogPlacement,
  type DialogPlacement,
} from "./dialog-position";
import styles from "./PublicLabScene.module.css";

interface AgentCharacterProps {
  lab: PublicLab;
  variant: "roaming" | "working";
}

const focusableSelector = [
  "a[href]",
  "button:not(:disabled)",
  "input:not(:disabled)",
  "select:not(:disabled)",
  "textarea:not(:disabled)",
  '[tabindex]:not([tabindex="-1"])',
].join(", ");

export function AgentCharacter({ lab, variant }: AgentCharacterProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [placement, setPlacement] = useState<DialogPlacement | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const titleId = useId();
  const descriptionId = useId();

  function closeDialog() {
    setIsOpen(false);
    triggerRef.current?.focus();
  }

  function trapDialogFocus(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key !== "Tab") {
      return;
    }

    const focusableElements = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(focusableSelector),
    );
    const firstFocusable = focusableElements.at(0);
    const lastFocusable = focusableElements.at(-1);

    if (!firstFocusable || !lastFocusable) {
      event.preventDefault();
      return;
    }

    if (event.shiftKey && document.activeElement === firstFocusable) {
      event.preventDefault();
      lastFocusable.focus();
    } else if (!event.shiftKey && document.activeElement === lastFocusable) {
      event.preventDefault();
      firstFocusable.focus();
    }
  }

  useEffect(() => {
    if (!isOpen) {
      return;
    }

    function handleEscape(event: KeyboardEvent) {
      if (event.key === "Escape") {
        setIsOpen(false);
        triggerRef.current?.focus();
      }
    }

    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [isOpen]);

  useLayoutEffect(() => {
    if (!isOpen) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    let frameId: number | null = null;

    document.body.style.overflow = "hidden";
    closeRef.current?.focus();

    function updatePlacement() {
      if (frameId !== null) {
        cancelAnimationFrame(frameId);
      }

      frameId = requestAnimationFrame(() => {
        frameId = null;
        const anchor = triggerRef.current?.getBoundingClientRect();
        const dialog = dialogRef.current?.getBoundingClientRect();

        if (!anchor || !dialog || dialog.width === 0 || dialog.height === 0) {
          setPlacement(null);
          return;
        }

        setPlacement(
          calculateDialogPlacement(anchor, dialog, {
            width: window.innerWidth,
            height: window.innerHeight,
          }),
        );
      });
    }

    updatePlacement();
    window.addEventListener("resize", updatePlacement);
    window.addEventListener("orientationchange", updatePlacement);
    window.addEventListener("scroll", updatePlacement, true);

    return () => {
      if (frameId !== null) {
        cancelAnimationFrame(frameId);
      }
      window.removeEventListener("resize", updatePlacement);
      window.removeEventListener("orientationchange", updatePlacement);
      window.removeEventListener("scroll", updatePlacement, true);
      document.body.style.overflow = previousOverflow;
    };
  }, [isOpen]);

  const dialogStyle: CSSProperties & Record<`--dialog-${string}`, string> = placement
    ? {
        "--dialog-left": `${placement.left}px`,
        "--dialog-top": `${placement.top}px`,
        "--dialog-tail-offset": `${placement.tailOffset}px`,
        left: "var(--dialog-left)",
        position: "fixed",
        top: "var(--dialog-top)",
      }
    : {};

  return (
    <article className={styles.character}>
      <button
        ref={triggerRef}
        className={styles.characterButton}
        type="button"
        aria-label={`${lab.manager.name}에게 말 걸기`}
        aria-haspopup="dialog"
        aria-expanded={isOpen}
        onClick={() => {
          setPlacement(null);
          setIsOpen(true);
        }}
      >
        <span className={styles[variant]} style={{ display: "grid", placeItems: "center" }}>
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
        </span>
      </button>

      {isOpen && typeof document !== "undefined"
        ? createPortal(
            <div className={styles.dialogLayer}>
              <div
                ref={dialogRef}
                className={styles.dialog}
                role="dialog"
                aria-modal="true"
                aria-labelledby={titleId}
                aria-describedby={descriptionId}
                onKeyDown={trapDialogFocus}
                data-placement={placement?.side}
                style={dialogStyle}
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
            </div>,
            document.body,
          )
        : null}
    </article>
  );
}
