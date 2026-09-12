import { useEffect, useRef } from "react";

import { SourceViewer } from "../search/SourceViewer";
import type { Evidence } from "./api";

export function EvidencePanel({ evidence, onClose }: { evidence: Evidence; onClose: () => void }) {
  const closeButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    closeButton.current?.focus();
    function handleKeyDown(event: globalThis.KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);
  return (
    <aside className="conversation-source-panel" role="dialog" aria-modal="true" aria-label="원문 근거">
      <div className="source-panel-toolbar"><strong>원문 근거</strong><button ref={closeButton} type="button" onClick={onClose}>원문 닫기</button></div>
      <SourceViewer assetVersionId={evidence.source.asset_version_id} projectionId={evidence.source.projection_id} highlights={evidence.highlights} page={evidence.source.location.page} />
    </aside>
  );
}
