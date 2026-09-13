"use client";

import { useRef, useState, type DragEvent, type HTMLAttributes } from "react";
import { MOVE_MIME, type MoveSource } from "./movement";

export interface PendingMove { source: MoveSource; destinationId: string | null; opener: HTMLElement | null }
export type MoveRowBindings = HTMLAttributes<HTMLElement> & { "data-drop-state"?: "allowed" | "forbidden" };

// Native payloads only identify this mounted session; they never contain commands.
export function useAssetMovement(enabled: boolean) {
  const [pending, setPending] = useState<PendingMove | null>(null);
  const [hover, setHover] = useState<{ id: string | null; allowed: boolean } | null>(null);
  const drag = useRef<{ token: string; source: MoveSource } | null>(null);
  const pendingRef = useRef<PendingMove | null>(null);

  function open(source: MoveSource | null, destinationId = source?.parentId ?? null, opener: HTMLElement | null = document.activeElement instanceof HTMLElement ? document.activeElement : null) {
    if (!enabled || !source || pendingRef.current) return;
    const next = { source, destinationId, opener };
    pendingRef.current = next; setPending(next);
  }
  function clear() { drag.current = null; pendingRef.current = null; setPending(null); setHover(null); }
  function endDrag() { drag.current = null; setHover(null); }
  function internal(event: DragEvent) { return enabled && drag.current && event.dataTransfer.types.includes(MOVE_MIME) && !event.dataTransfer.types.includes("Files"); }
  function sourceBindings(source: MoveSource | null): MoveRowBindings {
    return {
      draggable: enabled && !!source && !pending,
      onDragStart(event) {
        if (!enabled || !source || pendingRef.current) { event.preventDefault(); return; }
        const token = crypto.randomUUID(); drag.current = { token, source };
        event.dataTransfer.clearData(); event.dataTransfer.setData(MOVE_MIME, token); event.dataTransfer.effectAllowed = "move";
        event.stopPropagation();
      },
      onDragEnd: endDrag,
    };
  }
  function destinationBindings(id: string | null, ancestorIds: readonly string[] = []): MoveRowBindings {
    const valid = () => !!drag.current && !(drag.current.source.kind === "folder" && (drag.current.source.id === id || ancestorIds.includes(drag.current.source.id)));
    return {
      "data-drop-state": hover?.id === id ? hover.allowed ? "allowed" : "forbidden" : undefined,
      onDragOver(event) {
        event.preventDefault(); event.stopPropagation();
        const allowed = !!internal(event) && valid(); event.dataTransfer.dropEffect = allowed ? "move" : "none";
        setHover({ id, allowed });
      },
      onDragLeave(event) { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setHover(null); },
      onDrop(event) {
        event.preventDefault(); event.stopPropagation();
        const session = drag.current;
        if (internal(event) && valid() && session && event.dataTransfer.getData(MOVE_MIME) === session.token) open(session.source, id, event.currentTarget.querySelector<HTMLElement>("button"));
        endDrag();
      },
    };
  }
  return { pending, open, clear, sourceBindings, destinationBindings };
}
