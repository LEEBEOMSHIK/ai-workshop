"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../../shared/api/client";
import { routes } from "../../shared/routing/routes";
import {
  archiveRecord,
  getRecord,
  getRevision,
  listEvaluationOptions,
  listRecords,
  listTopics,
  restoreRecord,
  updateRecord,
  type EvaluationRun,
  type LearningDraft,
  type LearningRecord,
  type LearningSummary,
  type LearningTopic,
} from "./api";
import styles from "./Learning.module.css";
import { LearningEditor } from "./LearningEditor";
import { RecordBody } from "./RecordBody";

export function LearningRecordPage({ recordId }: { recordId: string }) {
  const [record, setRecord] = useState<LearningRecord | null>(null);
  const [loadedScope, setLoadedScope] = useState(recordId);
  const [topics, setTopics] = useState<LearningTopic[]>([]);
  const [records, setRecords] = useState<LearningSummary[]>([]);
  const [evaluations, setEvaluations] = useState<EvaluationRun[]>([]);
  const [historical, setHistorical] = useState<LearningRecord | null>(null);
  const [latest, setLatest] = useState<LearningRecord | null>(null);
  const [liveDraft, setLiveDraft] = useState<LearningDraft | null>(null);
  const [expectedRevision, setExpectedRevision] = useState(0);
  const [conflict, setConflict] = useState<{ action: "save" | "archive" | "restore"; message: string } | null>(null);
  const [editorDirty, setEditorDirty] = useState(false);
  const [editorGeneration, setEditorGeneration] = useState(0);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [actionPending, setActionPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);
  const historyRequestId = useRef(0);
  const latestRequestId = useRef(0);
  const actionRequestId = useRef(0);
  const actionInFlight = useRef(false);
  const activeRecordId = useRef(recordId);

  const load = useCallback(() => {
    const controller = new AbortController();
    const current = ++requestId.current;
    const scope = recordId;
    setLoading(true);
    setError(null);
    setLoadedScope(scope);
    setRecord(null);
    setLiveDraft(null);
    setEditorDirty(false);
    setHistorical(null);
    setLatest(null);
    setConflict(null);
    Promise.all([
      getRecord(recordId, controller.signal),
      listTopics(controller.signal),
      listRecords({ archived: false, limit: 100 }, controller.signal),
      listEvaluationOptions(controller.signal),
    ]).then(([loadedRecord, loadedTopics, loadedRecords, loadedEvaluations]) => {
      if (current !== requestId.current || activeRecordId.current !== scope) return;
      setRecord(loadedRecord);
      setLoadedScope(scope);
      setLiveDraft(loadedRecord.draft);
      setExpectedRevision(loadedRecord.revision);
      setTopics(loadedTopics);
      setRecords(loadedRecords.items.filter((item) => item.id !== recordId));
      setEvaluations(loadedEvaluations);
    }).catch((caught: unknown) => {
      if (!controller.signal.aborted && current === requestId.current && activeRecordId.current === scope) setError(errorMessage(caught));
    }).finally(() => {
      if (current === requestId.current && activeRecordId.current === scope) setLoading(false);
    });
    return () => controller.abort();
  }, [recordId]);

  useEffect(() => {
    activeRecordId.current = recordId;
    let dispose: (() => void) | undefined;
    const timer = window.setTimeout(() => { dispose = load(); }, 0);
    return () => {
      window.clearTimeout(timer);
      dispose?.();
    };
  }, [load, recordId]);

  const save = async (draft: LearningDraft) => {
    if (!record || actionInFlight.current) throw new Error("다른 작업을 처리하고 있습니다.");
    const currentAction = ++actionRequestId.current;
    const scope = recordId;
    actionInFlight.current = true;
    setActionPending(true);
    try {
      const saved = await updateRecord(recordId, expectedRevision, draft);
      if (currentAction !== actionRequestId.current || activeRecordId.current !== scope) return;
      setRecord(saved);
      setLiveDraft(saved.draft);
      setExpectedRevision(saved.revision);
      setEditorDirty(false);
      setEditorGeneration((value) => value + 1);
      setLatest(null);
      setConflict(null);
    } catch (caught) {
      if (currentAction === actionRequestId.current && activeRecordId.current === scope && isConflict(caught)) {
        setConflict({ action: "save", message: "다른 revision이 먼저 저장되었습니다. 입력은 그대로 유지됩니다." });
      }
      throw caught;
    } finally {
      actionInFlight.current = false;
      setActionPending(false);
    }
  };

  const loadLatest = async () => {
    const scope = recordId;
    const current = ++latestRequestId.current;
    try {
      const loaded = await getRecord(recordId);
      if (current === latestRequestId.current && activeRecordId.current === scope) setLatest(loaded);
    } catch (caught) {
      if (current === latestRequestId.current && activeRecordId.current === scope) setError(errorMessage(caught));
    }
  };

  const loadHistory = async (revision: number) => {
    if (!record) return;
    if (revision === record.revision) {
      ++historyRequestId.current;
      setHistorical(null);
      setHistoryLoading(false);
      return;
    }
    const current = ++historyRequestId.current;
    const scope = recordId;
    setHistoryLoading(true);
    try {
      const loaded = await getRevision(recordId, revision);
      if (current === historyRequestId.current && activeRecordId.current === scope) setHistorical(loaded);
    } catch (caught) {
      if (current === historyRequestId.current && activeRecordId.current === scope) setError(errorMessage(caught));
    } finally {
      if (current === historyRequestId.current && activeRecordId.current === scope) setHistoryLoading(false);
    }
  };

  const changeArchive = async (action: "archive" | "restore") => {
    if (!record || actionInFlight.current) return;
    if (action === "archive" && editorDirty && !window.confirm("저장하지 않은 편집 내용이 있습니다. 버리고 보관할까요?")) return;
    const currentAction = ++actionRequestId.current;
    const scope = recordId;
    const discardDraft = action === "archive" && editorDirty;
    actionInFlight.current = true;
    setActionPending(true);
    setError(null);
    try {
      const saved = action === "archive"
        ? await archiveRecord(recordId, record.revision)
        : await restoreRecord(recordId, record.revision);
      if (currentAction !== actionRequestId.current || activeRecordId.current !== scope) return;
      setRecord(saved);
      setExpectedRevision(saved.revision);
      if (discardDraft) {
        setLiveDraft(saved.draft);
        setEditorDirty(false);
        setEditorGeneration((value) => value + 1);
      }
      setConflict(null);
    } catch (caught) {
      if (currentAction === actionRequestId.current && activeRecordId.current === scope && isConflict(caught)) setConflict({ action, message: "보관 상태가 다른 revision에서 변경되었습니다. 최신 버전을 확인해 주세요." });
      else if (currentAction === actionRequestId.current && activeRecordId.current === scope) setError(errorMessage(caught));
    } finally {
      actionInFlight.current = false;
      setActionPending(false);
    }
  };

  const applyLatest = () => {
    if (!latest || !conflict) return;
    setExpectedRevision(latest.revision);
    setRecord(latest);
    if (!editorDirty) {
      setLiveDraft(latest.draft);
      setEditorGeneration((value) => value + 1);
    }
    setLatest(null);
    setConflict(null);
  };

  const showCurrent = () => {
    ++historyRequestId.current;
    setHistorical(null);
    setHistoryLoading(false);
  };

  if (loading || loadedScope !== recordId) return <main className={styles.shell}><p role="status">학습 기록을 불러오는 중…</p></main>;
  if (error && !record) return <main className={styles.shell}><div role="alert" className={styles.error}><p>{error}</p><button type="button" onClick={load}>다시 시도</button></div></main>;
  if (!record) return null;

  return (
    <main className={styles.shell}>
      <header className={styles.detailHeader}>
        <Link href={routes.workshopLearning}>학습 기록 목록</Link>
        <div><p className={styles.eyebrow}>{record.archived_at ? "보관된 기록" : "비공개 기록"}</p><h1>{record.draft.title}</h1><p>현재 revision {record.revision} · 수정 {formatDate(record.updated_at)}</p></div>
        <div className={styles.actions}>
          {record.archived_at
            ? <button type="button" disabled={actionPending} onClick={() => changeArchive("restore")}>{actionPending ? "처리 중…" : "기록 복원"}</button>
            : <button type="button" disabled={actionPending} onClick={() => changeArchive("archive")}>{actionPending ? "처리 중…" : "기록 보관"}</button>}
        </div>
      </header>

      {error ? <p className={styles.error} role="alert">{error}</p> : null}
      {conflict ? (
        <section className={styles.conflict} aria-labelledby="conflict-heading">
          <h2 id="conflict-heading">revision 충돌</h2>
          <p role="alert">{conflict.message}</p>
          <button type="button" onClick={loadLatest}>최신 버전 읽기</button>
          {latest ? <section className={styles.latest} aria-label="서버 최신 전체 내용"><h3>서버의 최신 revision {latest.revision}</h3><LearningEditor key={`${latest.id}-${latest.revision}`} initialDraft={latest.draft} topics={topics} learningRecords={records} evaluations={evaluations} referenceViews={latest.reference_views} datasetReferenceView={latest.dataset_reference_view} unavailableReferenceCount={latest.unavailable_reference_count} disabled submitLabel="" onSubmit={async () => undefined} /><button type="button" onClick={applyLatest}>{conflict.action === "save" ? `revision ${latest.revision}로 재기준화` : "최신 상태 적용"}</button></section> : null}
        </section>
      ) : null}

      <section className={styles.panel} aria-labelledby="history-heading">
        <div className={styles.sectionHeading}>
          <h2 id="history-heading">revision 이력</h2>
          <label>revision 보기<select value={historical?.revision ?? record.revision} onChange={(event) => loadHistory(Number(event.target.value))}>{Array.from({ length: record.revision }, (_, index) => index + 1).map((revision) => <option value={revision} key={revision}>{revision === record.revision ? `${revision} (현재)` : revision}</option>)}</select></label>
        </div>
        {historyLoading ? <p role="status">revision을 불러오는 중…</p> : null}
        {historical ? (
          <HistoricalRecord
            key={`${historical.id}-${historical.revision}`}
            record={historical}
            topics={topics}
            records={records}
            evaluations={evaluations}
            onCurrent={showCurrent}
          />
        ) : null}
      </section>

      <section className={styles.panel} aria-labelledby="editor-heading" hidden={Boolean(historical)}>
          <h2 id="editor-heading">기록 편집</h2>
          {record.archived_at ? <p className={styles.warning}>보관된 기록입니다. 복원한 뒤 편집할 수 있습니다.</p> : null}
          <LearningEditor
            key={`${recordId}-${editorGeneration}`}
            initialDraft={record.draft}
            topics={topics}
            learningRecords={records}
            evaluations={evaluations}
            referenceViews={record.reference_views}
            datasetReferenceView={record.dataset_reference_view}
            unavailableReferenceCount={record.unavailable_reference_count}
            disabled={Boolean(record.archived_at)}
            externallyPending={actionPending}
            submitLabel="변경 저장"
            onDirtyChange={setEditorDirty}
            onDraftChange={setLiveDraft}
            onSubmit={save}
          />
          <section className={styles.preview} aria-label="본문 미리보기"><h3>본문 미리보기</h3><RecordBody body={(liveDraft ?? record.draft).body} /></section>
      </section>
    </main>
  );
}

function HistoricalRecord({
  record,
  topics,
  records,
  evaluations,
  onCurrent,
}: {
  record: LearningRecord;
  topics: LearningTopic[];
  records: LearningSummary[];
  evaluations: EvaluationRun[];
  onCurrent: () => void;
}) {
  return (
    <article className={styles.history}>
      <div className={styles.sectionHeading}>
        <div><h3>revision {record.revision}</h3><p>{record.draft.title}</p></div>
        <button type="button" onClick={onCurrent}>현재 revision으로 돌아가기</button>
      </div>
      <LearningEditor
        initialDraft={record.draft}
        topics={topics}
        learningRecords={records}
        evaluations={evaluations}
        referenceViews={record.reference_views}
        datasetReferenceView={record.dataset_reference_view}
        unavailableReferenceCount={record.unavailable_reference_count}
        disabled
        submitLabel=""
        onSubmit={async () => undefined}
      />
      <RecordBody body={record.draft.body} />
    </article>
  );
}

function isConflict(error: unknown): boolean { return error instanceof ApiError && error.status === 409; }
function errorMessage(error: unknown): string { return error instanceof Error && error.message ? error.message : "요청을 완료하지 못했습니다."; }
function formatDate(value: string): string { return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
