"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { learningRecordPath } from "../../shared/routing/routes";
import {
  createRecord,
  listEvaluationOptions,
  listRecords,
  listTopics,
  type EvaluationRun,
  type LearningDraft,
  type LearningList,
  type LearningRecord,
  type LearningTopic,
  type RecordKind,
} from "./api";
import styles from "./Learning.module.css";
import { LearningEditor } from "./LearningEditor";
import { emptyExperiment, recordKindOptions } from "./registry";

interface LearningListPageProps {
  onCreated?: (record: LearningRecord) => void;
}

type ArchivedFilter = "false" | "true" | "all";

export function LearningListPage({ onCreated = defaultCreated }: LearningListPageProps) {
  const [topics, setTopics] = useState<LearningTopic[]>([]);
  const [evaluations, setEvaluations] = useState<EvaluationRun[]>([]);
  const [result, setResult] = useState<LearningList | null>(null);
  const [topicKey, setTopicKey] = useState("");
  const [kind, setKind] = useState<RecordKind | "">("");
  const [archived, setArchived] = useState<ArchivedFilter>("false");
  const [cursor, setCursor] = useState<string | undefined>();
  const [cursorStack, setCursorStack] = useState<Array<string | undefined>>([]);
  const [newKind, setNewKind] = useState<RecordKind | null>(null);
  const [newDraftDirty, setNewDraftDirty] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef(0);
  const createdRecord = useRef<LearningRecord | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([listTopics(controller.signal), listEvaluationOptions(controller.signal)])
      .then(([loadedTopics, loadedEvaluations]) => {
        setTopics(loadedTopics);
        setEvaluations(loadedEvaluations);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(caught, "선택 목록을 불러오지 못했습니다."));
      });
    return () => controller.abort();
  }, []);

  const load = useCallback(() => {
    const controller = new AbortController();
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    listRecords({
      ...(topicKey ? { topicKey } : {}),
      ...(kind ? { kind } : {}),
      ...(archived === "all" ? {} : { archived: archived === "true" }),
      ...(cursor ? { cursor } : {}),
    }, controller.signal)
      .then((next) => {
        if (currentRequest === requestId.current) setResult(next);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted && currentRequest === requestId.current) {
          setError(errorMessage(caught, "학습 기록을 불러오지 못했습니다."));
        }
      })
      .finally(() => {
        if (currentRequest === requestId.current) setLoading(false);
      });
    return () => controller.abort();
  }, [archived, cursor, kind, topicKey]);

  useEffect(() => {
    let dispose: (() => void) | undefined;
    const timer = window.setTimeout(() => { dispose = load(); }, 0);
    return () => { window.clearTimeout(timer); dispose?.(); };
  }, [load]);

  const resetFilter = (update: () => void) => {
    setCursor(undefined);
    setCursorStack([]);
    update();
  };

  const transitionNewDraft = (nextKind: RecordKind | null) => {
    if (nextKind === newKind) return;
    if (newKind && newDraftDirty && !window.confirm("저장하지 않은 작성 내용이 있습니다. 버릴까요?")) return;
    setNewDraftDirty(false);
    setNewKind(nextKind);
  };
  const beginNew = (nextKind: RecordKind) => transitionNewDraft(nextKind);
  const summaries = result?.items ?? [];
  const draftSeed = useMemo(() => newKind ? newDraft(newKind) : null, [newKind]);
  return (
    <main className={styles.shell}>
      <header className={styles.hero}>
        <p className={styles.eyebrow}>비공개 작업소</p>
        <h1>학습 기록</h1>
        <p>메모와 실험·문제 해결 과정을 비공개로 남기고, 실제 서비스와 평가를 참조합니다.</p>
        <p>학습 기록을 저장해도 모델 학습, 외부 전송 또는 공개가 실행되지는 않습니다.</p>
        <div className={styles.actions}>
          <button type="button" onClick={() => beginNew("note")}>새 메모</button>
          <button type="button" onClick={() => beginNew("experiment")}>새 실험</button>
        </div>
      </header>

      {newKind && draftSeed ? (
        <section className={styles.panel} aria-labelledby="new-record-heading">
          <div className={styles.sectionHeading}>
            <h2 id="new-record-heading">{newKind === "note" ? "새 메모" : "새 실험"}</h2>
            <button type="button" onClick={() => transitionNewDraft(null)}>작성 닫기</button>
          </div>
          <LearningEditor
            key={newKind}
            initialDraft={draftSeed}
            topics={topics}
            learningRecords={summaries}
            evaluations={evaluations}
            submitLabel="기록 저장"
            onDirtyChange={setNewDraftDirty}
            onSubmit={async (draft) => { createdRecord.current = await createRecord(draft); }}
            onSaved={() => {
              const created = createdRecord.current;
              createdRecord.current = null;
              if (created) onCreated(created);
            }}
          />
        </section>
      ) : null}

      <section className={styles.panel} aria-labelledby="records-heading">
        <div className={styles.sectionHeading}><h2 id="records-heading">내 기록</h2></div>
        <div className={styles.filters}>
          <label>주제 필터<select value={topicKey} onChange={(event) => resetFilter(() => setTopicKey(event.target.value))}><option value="">모든 주제</option>{topics.map((topic) => <option key={topic.key} value={topic.key}>{topic.label}</option>)}</select></label>
          <label>종류 필터<select value={kind} onChange={(event) => resetFilter(() => setKind(event.target.value as RecordKind | ""))}><option value="">모든 종류</option>{recordKindOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          <label>보관 상태<select value={archived} onChange={(event) => resetFilter(() => setArchived(event.target.value as ArchivedFilter))}><option value="false">현재 기록</option><option value="true">보관 기록</option><option value="all">전체</option></select></label>
        </div>
        {error ? <div className={styles.error} role="alert"><p>{error}</p><button type="button" onClick={load}>다시 시도</button></div> : null}
        {loading ? <p role="status">학습 기록을 불러오는 중…</p> : null}
        {!loading && !error && summaries.length === 0 ? <p className={styles.empty}>조건에 맞는 학습 기록이 없습니다.</p> : null}
        {!loading && !error && summaries.length > 0 ? (
          <div className={styles.cards}>
            {summaries.map((record) => (
              <article className={styles.card} key={record.id}>
                <div className={styles.cardMeta}><span>{kindLabel(record.kind)}</span><span>{record.archived_at ? "보관됨" : "편집 가능"}</span></div>
                <h3><Link href={learningRecordPath(record.id)}>{record.title}</Link></h3>
                <p>{record.topic_keys.map((key) => topics.find((topic) => topic.key === key)?.label).filter(Boolean).join(" · ") || "주제 미지정"}</p>
                <time dateTime={record.updated_at}>수정 {formatDate(record.updated_at)}</time>
              </article>
            ))}
          </div>
        ) : null}
        <nav className={styles.pagination} aria-label="학습 기록 페이지">
          <button type="button" disabled={cursorStack.length === 0 || loading} onClick={() => { const previous = cursorStack.at(-1); setCursorStack((stack) => stack.slice(0, -1)); setCursor(previous); }}>이전 페이지</button>
          <button type="button" disabled={!result?.next_cursor || loading} onClick={() => { setCursorStack((stack) => [...stack, cursor]); setCursor(result?.next_cursor ?? undefined); }}>다음 페이지</button>
        </nav>
      </section>
    </main>
  );
}

function newDraft(kind: RecordKind): LearningDraft {
  return { title: "", body: "", kind, topic_keys: [], domain_labels: [], experiment: kind === "experiment" ? emptyExperiment() : null, references: [] };
}
function kindLabel(kind: RecordKind): string { return recordKindOptions.find((option) => option.value === kind)?.label ?? kind; }
function formatDate(value: string): string { return new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value)); }
function errorMessage(error: unknown, fallback: string): string { return error instanceof Error && error.message ? error.message : fallback; }
function defaultCreated(record: LearningRecord) { window.location.assign(learningRecordPath(record.id)); }
