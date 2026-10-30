"use client";

import { createContext, useContext, useId, useImperativeHandle, useLayoutEffect, useRef, useState,
  type CSSProperties, type Dispatch, type ReactNode, type RefObject, type SetStateAction } from "react";
import styles from "./AgentSpanModal.module.css";

type OpenHelp = { id: string } | null;
export type AgentHelpController = { dismiss: () => boolean };
const HelpContext = createContext<{ active: OpenHelp; setActive: Dispatch<SetStateAction<OpenHelp>> } | null>(null);

export function AgentPurposeHelpProvider({ controller, children }: {
  controller: RefObject<AgentHelpController | null>; children: ReactNode;
}) {
  const [active, setActive] = useState<OpenHelp>(null);
  useImperativeHandle(controller, () => ({ dismiss() {
    if (!active) return false;
    setActive(null);
    return true;
  } }), [active]);
  return <HelpContext.Provider value={{ active, setActive }}>{children}</HelpContext.Provider>;
}

export function AgentPurposeHelp({ title, text }: { title: string; text: string }) {
  const context = useContext(HelpContext);
  const id = useId();
  const root = useRef<HTMLSpanElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const tooltip = useRef<HTMLDivElement>(null);
  const hovering = useRef(false);
  const keyboardFocused = useRef(false);
  const pointerFocus = useRef(false);
  const [position, setPosition] = useState<CSSProperties | null>(null);
  const open = context?.active?.id === id;
  useLayoutEffect(() => {
    if (!open || !button.current || !tooltip.current) return;
    const anchor = button.current;
    const box = tooltip.current;
    function measure() {
      const rect = anchor.getBoundingClientRect();
      const dialog = anchor.closest('[role="dialog"]')?.getBoundingClientRect();
      const margin = 12;
      const width = Math.min(360, window.innerWidth - margin * 2, (dialog?.width || window.innerWidth) - margin * 2);
      const left = Math.max(margin, Math.min(rect.right - width, window.innerWidth - margin - width));
      const below = Math.max(0, window.innerHeight - margin - rect.bottom);
      const above = Math.max(0, rect.top - margin);
      const boxRect = box.getBoundingClientRect();
      const naturalHeight = box.scrollHeight + Math.max(0, boxRect.height - box.clientHeight);
      const useBelow = naturalHeight <= below || below >= above;
      const available = useBelow ? below : above;
      const height = Math.min(naturalHeight, available);
      setPosition({ left, width: Math.max(0, width), top: useBelow ? rect.bottom : rect.top - height,
        maxHeight: available, visibility: available > 0 ? "visible" : "hidden" });
    }
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(measure);
    observer?.observe(anchor); observer?.observe(box);
    return () => {
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
      observer?.disconnect();
    };
  }, [open]);
  if (!context) return null;
  const show = () => context.setActive(current => current?.id === id ? current : { id });
  const close = () => context.setActive(current => current?.id === id ? null : current);
  return <span ref={root} className={styles.helpAnchor}
    onPointerDown={() => { pointerFocus.current = true; keyboardFocused.current = false; }}
    onMouseEnter={() => { hovering.current = true; show(); }}
    onMouseLeave={event => {
      if (event.relatedTarget instanceof Node && root.current?.contains(event.relatedTarget)) return;
      hovering.current = false;
      if (!keyboardFocused.current) close();
    }}
    onFocus={() => {
      keyboardFocused.current = !pointerFocus.current;
      if (keyboardFocused.current) show();
    }}
    onBlur={event => {
      if (event.relatedTarget instanceof Node && root.current?.contains(event.relatedTarget)) return;
      keyboardFocused.current = false; pointerFocus.current = false;
      if (!hovering.current) close();
    }}>
    <button ref={button} type="button" aria-label={`${title} 도움말`} aria-expanded={open}
      aria-describedby={open ? id : undefined} className={styles.helpButton}
      onKeyDown={event => {
        if (event.key === "Enter" || event.key === " ") {
          pointerFocus.current = false; keyboardFocused.current = true; show();
        }
      }}
      onClick={event => event.stopPropagation()}>?</button>
    {open ? <div ref={tooltip} id={id} role="tooltip" className={styles.helpTooltip}
      style={position ?? { visibility: "hidden" }}><strong>{title}</strong><p>{text}</p></div> : null}
  </span>;
}
