import { useEffect, useRef } from "react";

import { SourceViewer } from "../search/SourceViewer";
import type { Evidence } from "./api";

export function EvidencePanel({ evidence, onClose }: { evidence: Evidence; onClose: () => void }) {
  const closeButton = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    closeButton.current?.focus();
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab") {
        const controls = Array.from(panel.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex="0"]',
        ) ?? []);
        const first = controls[0], last = controls.at(-1);
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => { document.removeEventListener("keydown", handleKeyDown); if (previous?.isConnected) previous.focus(); };
  }, [onClose]);
  return (
    <aside ref={panel} className="conversation-source-panel" role="dialog" aria-modal="true" aria-label="원문 근거">
      <div className="source-panel-toolbar"><strong>원문 근거</strong><button ref={closeButton} type="button" onClick={onClose}>원문 닫기</button></div>
      <SourceViewer assetVersionId={evidence.source.asset_version_id} projectionId={evidence.source.projection_id} highlights={evidence.highlights} page={evidence.source.location.page} />
    </aside>
  );
}
