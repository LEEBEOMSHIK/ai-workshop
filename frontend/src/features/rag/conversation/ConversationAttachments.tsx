import { useEffect, useRef, useState } from "react";
import type { DocumentSummary } from "../../assets/api";
import { excludeDraftAttachment, getAttachmentDraft, getAttachmentOptions, getDraftAttachmentOptions, listDraftAttachments, listAttachments, uploadDraftAttachment, uploadAttachment, type Attachment, type AttachmentOptions, type AttachmentDraft } from "./sessions-api";

export function ConversationAttachments({slug, sessionId, draftId = null, ensureDraft, onDraft, onBusy, onSelect, pendingFiles, onFilesConsumed}: {
  slug: string; sessionId: string | null; draftId?: string | null; ensureDraft: () => Promise<AttachmentDraft>; onDraft?: (draft: AttachmentDraft) => void;
  onBusy: (busy: boolean) => void; onSelect: (documents: DocumentSummary[]) => void;
  pendingFiles?: File[]; onFilesConsumed?: () => void;
}) {
  const [options, setOptions] = useState<AttachmentOptions | null>(null);
  const [workspaceId, setWorkspaceId] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [uploading, setUploading] = useState(false);
  const uploadingRef = useRef(false);
  const [queue, setQueue] = useState<File[]>([]);
  const queueRef = useRef<File[]>([]);
  const consumedBatch = useRef<File[] | undefined>(undefined);
  const pendingRows = useRef(new Set<string>());
  const [error, setError] = useState("");
  const context = useRef({sessionId, draftId});
  const previousContext = useRef({sessionId, draftId});
  useEffect(() => { context.current = {sessionId, draftId}; }, [sessionId, draftId]);
  const operation = useRef(0);
  const [excluding, setExcluding] = useState(false);
  const excludingRef = useRef(false);
  const alive = useRef(true);
  const uploaded = useRef(new Set<string>());
  const excluded = useRef(new Set<string>());
  const callbacks = useRef({ensureDraft, onDraft, onBusy, onSelect, onFilesConsumed});
  useEffect(() => { callbacks.current = {ensureDraft, onDraft, onBusy, onSelect, onFilesConsumed}; });

  function updateQueue(files: File[]) {
    queueRef.current = files;
    setQueue(files);
    callbacks.current.onBusy(files.length > 0 || uploadingRef.current || excludingRef.current || pendingRows.current.size > 0);
  }

  useEffect(() => {
    if (!pendingFiles?.length || consumedBatch.current === pendingFiles) return;
    consumedBatch.current = pendingFiles;
    queueRef.current = [...queueRef.current, ...pendingFiles];
    setQueue(queueRef.current);
    callbacks.current.onBusy(true);
    callbacks.current.onFilesConsumed?.();
  }, [pendingFiles]);

  useEffect(() => {
    const previous = previousContext.current;
    // null -> first draft is the same queued-file intent. Other ID transitions
    // fence in-flight upload/exclusion results before starting this parent's poll.
    if ((previous.sessionId || previous.draftId) && (previous.sessionId !== sessionId || previous.draftId !== draftId)) {
      operation.current += 1; uploadingRef.current = false; excludingRef.current = false; setUploading(false);
      queueRef.current = []; setQueue([]); pendingRows.current.clear(); uploaded.current.clear(); excluded.current.clear(); setAttachments([]); setWorkspaceId(""); setOptions(null); setError(""); setExcluding(false);
    }
    previousContext.current = {sessionId, draftId};
    const controller = new AbortController();
    const owner = {sessionId, draftId};
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function refresh(id: string) {
      try {
        const rows = await (owner.sessionId ? listAttachments(slug, id, controller.signal) : listDraftAttachments(slug, id, controller.signal));
        if (controller.signal.aborted) return;
        const visible = rows.filter(row => !row.excluded_at && !excluded.current.has(row.id));
        setAttachments(visible);
        const ready = rows.flatMap(row => !row.excluded_at && !excluded.current.has(row.id) && row.status === "ready" && row.document?.status === "ready" && !row.error_code && uploaded.current.delete(row.id) ? [row.document] : []);
        for (const row of rows) {
          if (row.status === "stored" || row.status === "failed") uploaded.current.delete(row.id);
        }
        if (ready.length) callbacks.current.onSelect(ready);
        const busy = rows.some(row => row.status === "uploading") || visible.some(row => row.status === "uploading" || row.status === "processing");
        pendingRows.current = new Set(visible.filter(row => row.status === "uploading" || row.status === "processing").map(row => row.id));
        callbacks.current.onBusy(uploadingRef.current || excludingRef.current || queueRef.current.length > 0 || busy);
        timer = setTimeout(() => void refresh(id), busy ? 2000 : 5000);
      } catch { if (!controller.signal.aborted) setError("첨부 처리 상태를 확인하지 못했습니다. 대화를 다시 열어 확인해 주세요."); }
    }
    void (async () => {
      const id = owner.sessionId ?? owner.draftId;
      const result = owner.sessionId ? await getAttachmentOptions(slug, owner.sessionId, controller.signal)
        : owner.draftId ? await getDraftAttachmentOptions(slug, owner.draftId, controller.signal)
        : await getAttachmentOptions(slug, null, controller.signal);
      if (controller.signal.aborted) return;
      setOptions(result); if (result.workspaces.length === 1) setWorkspaceId(result.workspaces[0].id);
      if (id) await refresh(id);
    })().catch(() => { if (!controller.signal.aborted) setError("첨부 위치를 확인하지 못했습니다."); });
    return () => { controller.abort(); clearTimeout(timer); };
  }, [slug, sessionId, draftId]);

  useEffect(() => {
    alive.current = true;
    return () => { alive.current = false; operation.current += 1; };
  }, []);

  useEffect(() => {
    const file = queue[0];
    if (!file || !workspaceId || uploadingRef.current || excluding) return;
    const owner = ++operation.current;
    const original = {...context.current};
    uploadingRef.current = true; setUploading(true); setError(""); callbacks.current.onBusy(true);
    void (async () => {
    try {
      const currentDraft = original.sessionId ? null : await callbacks.current.ensureDraft();
      if (!alive.current || operation.current !== owner) return;
      const latest = currentDraft ? await getAttachmentDraft(slug, currentDraft.id) : null;
      if (!alive.current || operation.current !== owner) return;
      const row = original.sessionId ? await uploadAttachment(slug, original.sessionId, workspaceId, file)
        : await uploadDraftAttachment(slug, latest!, workspaceId, file);
      if (!alive.current || operation.current !== owner) return;
      if (latest) {
        const updated = await getAttachmentDraft(slug, latest.id);
        if (!alive.current || operation.current !== owner) return;
        callbacks.current.onDraft?.(updated);
      }
      setAttachments(current => [...current.filter(item => item.id !== row.id), row]);
      if (row.status === "ready" && row.document?.status === "ready" && !row.error_code) callbacks.current.onSelect([row.document]);
      else if (row.status === "uploading" || row.status === "processing") { uploaded.current.add(row.id); pendingRows.current.add(row.id); }
    } catch { if (alive.current && operation.current === owner) setError("파일을 첨부하지 못했습니다. 처리 상태를 확인한 뒤 다시 시도해 주세요."); }
    finally {
      if (alive.current && operation.current === owner) {
        uploadingRef.current = false;
        queueRef.current = queueRef.current.slice(1);
        setQueue(queueRef.current);
        setUploading(false);
        callbacks.current.onBusy(queueRef.current.length > 0 || pendingRows.current.size > 0);
      }
    }
    })();
  }, [queue, slug, workspaceId, excluding]);

  async function exclude(row: Attachment) {
    const owner = operation.current;
    const id = context.current.draftId;
    excludingRef.current = true; setExcluding(true); callbacks.current.onBusy(true);
    try {
      if (id) {
        const latest = await getAttachmentDraft(slug, id);
        const updated = await excludeDraftAttachment(slug, latest, row.id);
        if (!alive.current || operation.current !== owner || context.current.draftId !== id) return;
        callbacks.current.onDraft?.(updated);
      }
      if (!alive.current || operation.current !== owner) return;
      excluded.current.add(row.id); uploaded.current.delete(row.id); pendingRows.current.delete(row.id);
      const remaining = attachments.filter(item => item.id !== row.id); setAttachments(remaining);
      callbacks.current.onBusy(uploadingRef.current || queueRef.current.length > 0 || row.status === "uploading" || remaining.some(item => item.status === "uploading" || item.status === "processing"));
    } catch {
      if (alive.current && operation.current === owner) { setError("첨부 제외를 저장하지 못했습니다. 처리 상태를 확인한 뒤 다시 시도해 주세요."); callbacks.current.onBusy(uploadingRef.current || queueRef.current.length > 0 || pendingRows.current.size > 0); }
    } finally { if (alive.current && operation.current === owner) { excludingRef.current = false; setExcluding(false); } }
  }

  async function selectReady(id: string) {
    const owner = operation.current;
    const parent = {...context.current};
    try {
      const rows = parent.sessionId ? await listAttachments(slug, parent.sessionId)
        : parent.draftId ? await listDraftAttachments(slug, parent.draftId) : [];
      if (!alive.current || operation.current !== owner || context.current.sessionId !== parent.sessionId || context.current.draftId !== parent.draftId) return;
      setAttachments(rows.filter(row => !row.excluded_at && !excluded.current.has(row.id)));
      const row = rows.find(row => row.id === id && !row.excluded_at && !excluded.current.has(row.id));
      if (row?.status === "ready" && row.document?.status === "ready" && !row.error_code) callbacks.current.onSelect([row.document]);
      else setError("첨부 문서의 현재 권한 또는 검색 준비 상태가 변경되었습니다. 상태를 다시 확인해 주세요.");
    } catch { if (alive.current && operation.current === owner) setError("첨부 문서의 현재 권한을 확인하지 못했습니다. 다시 시도해 주세요."); }
  }

  return <section className="conversation-attachments" aria-label="PC 파일 첨부">
    {error ? <p role="alert">{error}</p> : null}
    {!options && !error ? <p role="status">첨부 위치를 확인하는 중…</p> : null}
    {options?.workspaces.length === 0 ? <p role="status">첨부할 수 있는 개인 공간이 없습니다. 본인 소유이며 쓰기 가능한 개인 또는 유효한 임시 공간이 필요합니다.</p> : null}
    {options && options.workspaces.length > 1 ? <label>첨부 저장 위치<select value={workspaceId} disabled={uploading} onChange={event => setWorkspaceId(event.target.value)}><option value="">위치 선택</option>{options.workspaces.map(workspace => <option key={workspace.id} value={workspace.id}>{workspace.name}</option>)}</select></label> : null}
    <input hidden aria-label="PC 파일 선택" type="file" multiple disabled={!workspaceId || uploading || excluding} onChange={event => { const files = Array.from(event.target.files ?? []); if (files.length) updateQueue([...queueRef.current, ...files]); event.target.value = ""; }} />
    {queue.length ? <ul className="conversation-attachment-queue">{queue.map((file, index) => <li key={`${file.name}-${index}`}><span>{file.name}</span><small role="status">{index === 0 && uploading ? "파일을 올리는 중…" : "첨부 대기"}</small>{index !== 0 || !uploading ? <button type="button" aria-label={`${file.name} 첨부 취소`} onClick={() => updateQueue(queueRef.current.filter((_, position) => position !== index))}>취소</button> : null}</li>)}</ul> : null}
    <ul>{attachments.map(row => <li key={row.id}><span>{row.document?.name ?? "첨부 파일"} · {({uploading: "업로드 중", processing: "검색 준비 중", ready: "검색 가능", stored: "저장됨 · 현재 답변에 사용 불가", failed: "처리 실패"} as Record<string, string>)[row.status] ?? row.status}</span>{row.status === "ready" && row.document?.status === "ready" && !row.error_code ? <button type="button" onClick={() => void selectReady(row.id)}>질문에 추가</button> : null}{row.status !== "ready" ? <button type="button" disabled={uploading || excluding} onClick={() => void exclude(row)}>제외</button> : null}{row.error_code ? <small>{row.error_code === "attachment_outside_generation_scope" ? "현재 대화의 검색·생성 범위에 포함되지 않은 개인 파일입니다." : row.error_code}</small> : null}</li>)}</ul>
  </section>;
}
