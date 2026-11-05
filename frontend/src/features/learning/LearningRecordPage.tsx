"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../../shared/api/client";
import { routes } from "../../shared/routing/routes";
import { Button } from "../../shared/ui/Button";
import {
  archiveRecord,
  getRecord,
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
import { LearningRecordReader } from "./LearningRecordReader";
import { RecordBody } from "./RecordBody";
import { experimentStatusOptions, recordKindOptions } from "./registry";


export function LearningRecordPage({ recordId }: { recordId: string }) {
  const [record, setRecord] = useState<LearningRecord | null>(null);
  const [loadedScope, setLoadedScope] = useState(recordId);
  const [topics, setTopics] = useState<LearningTopic[]>([]);
  const [records, setRecords] = useState<LearningSummary[]>([]);
  const [evaluations, setEvaluations] = useState<EvaluationRun[]>([]);
  const [latest, setLatest] = useState<LearningRecord | null>(null);
  const [liveDraft, setLiveDraft] = useState<LearningDraft | null>(null);
  const [expectedRevision, setExpectedRevision] = useState(0);
  const [conflict, setConflict] = useState<{ action: "save" | "archive" | "restore"; message: string } | null>(null);
  const [editorDirty, setEditorDirty] = useState(false);
  const [editing, setEditing] = useState(false);
  const [editorGeneration, setEditorGeneration] = useState(0);
  const [loading, setLoading] = useState(true);
  const [actionPending, setActionPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);
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
    setEditing(false);
    setLiveDraft(null);
    setEditorDirty(false);
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
      setEditing(false);
      setExpectedRevision(saved.revision);
      setEditorDirty(false);
      setEditorGeneration((value) => value + 1);
      setLatest(null);
      setConflict(null);
    } catch (caught) {
      if (currentAction === actionRequestId.current && activeRecordId.current === scope && isConflict(caught)) {
        setConflict({ action: "save", message: "다른 변경 사항이 먼저 저장되었습니다. 입력한 내용과 비교해 주세요." });
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
      if (action === "archive") setEditing(false);
      if (discardDraft) {
        setLiveDraft(saved.draft);
        setEditorDirty(false);
        setEditorGeneration((value) => value + 1);
      }
      setConflict(null);
    } catch (caught) {
      if (currentAction === actionRequestId.current && activeRecordId.current === scope && isConflict(caught)) setConflict({ action, message: "보관 상태가 변경되었습니다. 현재 저장된 내용을 확인해 주세요." });
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

  if (loading || loadedScope !== recordId) return <main className={styles.shell}><p role="status">학습 기록을 불러오는 중…</p></main>;
  if (error && !record) return <main className={styles.shell}><div role="alert" className={styles.error}><p>{error}</p><Button onClick={load}>다시 시도</Button></div></main>;
  if (!record) return null;
  const experimentStatus = record.draft.experiment?.status;

  return (
    <main className={`${styles.shell} ${styles.recordShell}`}>
      <header className={styles.recordHeader}>
        <div className={styles.recordToolbar}>
          <Link className={styles.backLink} href={routes.workshopLearning}><span aria-hidden="true">←</span> 학습 기록 목록</Link>
          <div className={styles.actions}>
            {editing ? (
              <Button disabled={actionPending} onClick={() => setEditing(false)}>읽기 보기</Button>
            ) : !record.archived_at && (
              <Button variant="primary" aria-label="기록 편집" disabled={actionPending} onClick={() => setEditing(true)}>편집</Button>
            )}
            {record.archived_at
              ? <Button variant="primary" disabled={actionPending} onClick={() => changeArchive("restore")}>{actionPending ? "처리 중…" : "기록 복원"}</Button>
              : <Button variant="quiet" disabled={actionPending} onClick={() => changeArchive("archive")}>{actionPending ? "처리 중…" : "기록 보관"}</Button>}
          </div>
        </div>
        <h1>{record.draft.title}</h1>
        <div className={styles.recordSummary}>
          <dl className={styles.recordClassification} aria-label="분류 및 실험 상태">
            <div><dt>기록 종류</dt><dd>{recordKindOptions.find(option => option.value === record.draft.kind)?.label ?? record.draft.kind}</dd></div>
            {record.draft.topic_keys.length > 0 && <div><dt>기술 주제</dt><dd>{record.draft.topic_keys.map(key => topics.find(topic => topic.key === key)?.label ?? key).join(", ")}</dd></div>}
            {record.draft.domain_labels.length > 0 && <div><dt>도메인 분류</dt><dd>{record.draft.domain_labels.join(", ")}</dd></div>}
            {experimentStatus && <div><dt>실험 상태</dt><dd>{experimentStatusOptions.find(option => option.value === experimentStatus)?.label}</dd></div>}
          </dl>
          <p className={styles.recordMeta}>
            <span><MetaIcon kind="lock" />비공개 기록</span>
            <span><MetaIcon kind="clock" />수정 <time dateTime={record.updated_at}>{formatDate(record.updated_at)}</time></span>
            {record.archived_at && <span>보관된 기록</span>}
          </p>
        </div>
      </header>
      {record.archived_at && <p className={styles.warning}>보관된 기록입니다. 복원한 뒤 편집할 수 있습니다.</p>}
      {!editing && editorDirty && <p role="status">저장 전 편집 내용이 있습니다. 편집을 열어 이어서 작성하세요.</p>}

      {error ? <p className={styles.error} role="alert">{error}</p> : null}
      {conflict ? (
        <section className={styles.conflict} aria-labelledby="conflict-heading">
          <h2 id="conflict-heading">다른 변경 사항이 있습니다</h2>
          <p role="alert">{conflict.message}</p>
          <Button onClick={loadLatest}>저장된 내용 확인</Button>
          {latest ? <section className={styles.latest} aria-label="서버 최신 전체 내용"><h3>현재 저장된 내용</h3><LearningEditor key={`${latest.id}-${latest.revision}`} initialDraft={latest.draft} topics={topics} learningRecords={records} evaluations={evaluations} referenceViews={latest.reference_views} datasetReferenceView={latest.dataset_reference_view} unavailableReferenceCount={latest.unavailable_reference_count} disabled submitLabel="" onSubmit={async () => undefined} /><Button onClick={applyLatest}>{conflict.action === "save" ? "현재 내용을 기준으로 편집 계속" : "최신 상태 적용"}</Button></section> : null}
        </section>
      ) : null}

      {!editing && (
        <section className={styles.readingPanel} aria-label="기록 읽기">
          <LearningRecordReader record={record} records={records} evaluations={evaluations} />
        </section>
      )}

      {(editing || editorDirty) && <section className={styles.panel} aria-labelledby="editor-heading" hidden={!editing}>
          <h2 id="editor-heading">기록 편집</h2>
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
      </section>}
    </main>
  );
}

function isConflict(error: unknown): boolean { return error instanceof ApiError && error.status === 409; }
function errorMessage(error: unknown): string { return error instanceof Error && error.message ? error.message : "요청을 완료하지 못했습니다."; }
function formatDate(value: string): string { return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }

function MetaIcon({ kind }: { kind: "lock" | "clock" }) {
  return <svg aria-hidden="true" width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    {kind === "lock" ? <><rect x="5" y="10" width="14" height="11" rx="2.5" /><path d="M8 10V7a4 4 0 0 1 8 0v3m-4 5v2" /></>
      : <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>}
  </svg>;
}
