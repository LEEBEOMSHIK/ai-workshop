import { useEffect, useRef, useState } from "react";
import type { DocumentSummary } from "../../assets/api";
import { getAttachmentOptions, listAttachments, uploadAttachment, type Attachment, type AttachmentOptions, type ConversationDetail } from "./sessions-api";

export function ConversationAttachments({slug, sessionId, ensureSession, onBusy, onSelect}: {
  slug: string; sessionId: string | null; ensureSession: () => Promise<ConversationDetail>;
  onBusy: (busy: boolean) => void; onSelect: (documents: DocumentSummary[]) => void;
}) {
  const [options, setOptions] = useState<AttachmentOptions | null>(null);
  const [workspaceId, setWorkspaceId] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const uploadingRef = useRef(false);
  const pendingRows = useRef(new Set<string>());
  const [error, setError] = useState("");
  const activeSession = useRef(sessionId);
  const alive = useRef(true);
  const uploaded = useRef(new Set<string>());
  const excluded = useRef(new Set<string>());
  const callbacks = useRef({ensureSession, onBusy, onSelect});
  useEffect(() => { callbacks.current = {ensureSession, onBusy, onSelect}; });

  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function refresh(id: string) {
      try {
        const rows = await listAttachments(slug, id, controller.signal);
        if (controller.signal.aborted) return;
        const visible = rows.filter(row => !excluded.current.has(row.id));
        setAttachments(visible);
        const ready = rows.flatMap(row => row.status === "ready" && row.document && uploaded.current.delete(row.id) ? [row.document] : []);
        if (ready.length) callbacks.current.onSelect(ready);
        const busy = visible.some(row => row.status === "uploading" || row.status === "processing");
        pendingRows.current = new Set(visible.filter(row => row.status === "uploading" || row.status === "processing").map(row => row.id));
        callbacks.current.onBusy(uploadingRef.current || busy);
        timer = setTimeout(() => void refresh(id), busy ? 2000 : 5000);
      } catch { if (!controller.signal.aborted) setError("첨부 처리 상태를 확인하지 못했습니다. 대화를 다시 열어 확인해 주세요."); }
    }
    void (async () => {
      const id = activeSession.current ?? (await callbacks.current.ensureSession()).id;
      activeSession.current = id;
      const result = await getAttachmentOptions(slug, id);
      if (controller.signal.aborted) return;
      setOptions(result); if (result.workspaces.length === 1) setWorkspaceId(result.workspaces[0].id);
      await refresh(id);
    })().catch(() => { if (!controller.signal.aborted) setError("첨부 위치를 확인하지 못했습니다."); });
    return () => { alive.current = false; controller.abort(); clearTimeout(timer); callbacks.current.onBusy(false); };
  }, [slug]);

  async function upload(file: File) {
    if (!workspaceId || !activeSession.current || uploading) return;
    uploadingRef.current = true; setUploading(true); setError(""); callbacks.current.onBusy(true);
    try {
      const row = await uploadAttachment(slug, activeSession.current, workspaceId, file);
      if (!alive.current) return;
      setAttachments(current => [...current.filter(item => item.id !== row.id), row]);
      if (row.status === "ready" && row.document) callbacks.current.onSelect([row.document]);
      else if (row.status !== "failed") { uploaded.current.add(row.id); pendingRows.current.add(row.id); }
    } catch { if (alive.current) setError("파일을 첨부하지 못했습니다. 처리 상태를 확인한 뒤 다시 시도해 주세요."); }
    finally { uploadingRef.current = false; if (alive.current) { setUploading(false); callbacks.current.onBusy(pendingRows.current.size > 0); } }
  }

  return <section className="conversation-attachments" aria-label="PC 파일 첨부">
    <p>이 대화의 비공개 첨부</p>
    {error ? <p role="alert">{error}</p> : null}
    {!options && !error ? <p role="status">첨부 위치를 확인하는 중…</p> : null}
    {options?.workspaces.length === 0 ? <p role="status">첨부할 수 있는 개인 공간이 없습니다. 도메인에 허용된 쓰기 가능한 비공개 공간이 필요합니다.</p> : null}
    {options && options.workspaces.length > 1 ? <label>첨부 저장 위치<select value={workspaceId} disabled={uploading} onChange={event => setWorkspaceId(event.target.value)}><option value="">위치 선택</option>{options.workspaces.map(workspace => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}</select></label> : null}
    <label className="conversation-upload">PC 파일 선택<input type="file" disabled={!workspaceId || uploading} onChange={event => { const file = event.target.files?.[0]; if (file) void upload(file); event.target.value = ""; }} /></label>
    {uploading ? <p role="status">파일을 올리는 중…</p> : null}
    <ul>{attachments.map(row => <li key={row.id}><span>{row.document?.name ?? "첨부 파일"} · {({uploading: "업로드 중", processing: "검색 준비 중", ready: "검색 가능", failed: "처리 실패"} as Record<string, string>)[row.status] ?? row.status}</span>{row.status === "ready" && row.document ? <button type="button" onClick={() => onSelect([row.document!])}>질문에 추가</button> : null}{row.status !== "ready" ? <button type="button" onClick={() => {
      excluded.current.add(row.id); uploaded.current.delete(row.id);
      pendingRows.current.delete(row.id);
      const remaining = attachments.filter(item => item.id !== row.id); setAttachments(remaining);
      callbacks.current.onBusy(uploadingRef.current || remaining.some(item => item.status === "uploading" || item.status === "processing"));
    }}>제외</button> : null}{row.error_code ? <small>{row.error_code}</small> : null}</li>)}</ul>
  </section>;
}
