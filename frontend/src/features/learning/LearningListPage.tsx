"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { learningRecordPath } from "../../shared/routing/routes";
import { Pagination } from "../../shared/ui/Pagination";
import { SelectField } from "../../shared/ui/Fields";
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
import { LearningSequenceList } from "./LearningSequence";
import { defaultLearningPageSize, emptyExperiment, learningPageSizeOptions, recordKindOptions, type LearningPageSize } from "./registry";

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
  const [sort, setSort] = useState<"learning_latest" | "learning_order" | "updated">("learning_latest");
  const [pageSize, setPageSize] = useState<LearningPageSize>(defaultLearningPageSize);
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
      sort,
      limit: pageSize,
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
  }, [archived, cursor, kind, pageSize, sort, topicKey]);

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
        <div className={styles.sectionHeading}><h2 id="records-heading">내 기록</h2>
          <SelectField label="정렬" value={sort} onChange={(event) => resetFilter(() => setSort(event.target.value as typeof sort))}>
            <option value="learning_latest">학습 흐름별 최신순</option><option value="learning_order">학습 흐름별 처음부터</option><option value="updated">최근 수정순</option>
          </SelectField>
        </div>
        <p className={styles.sequenceHint}>{sort === "updated"
          ? "최근 수정한 기록부터 표시합니다. 학습 차수와 실행일은 각 기록에서 확인할 수 있습니다."
          : `${sort === "learning_latest" ? "각 흐름에서 최신 학습부터" : "각 흐름에서 처음 학습부터"} 표시합니다. 출발점과 결과는 기록된 내용을 사용하며, 관련 계획은 따로 구분합니다.`}</p>
        <div className={styles.filters}>
          <label>주제 필터<select value={topicKey} onChange={(event) => resetFilter(() => setTopicKey(event.target.value))}><option value="">모든 주제</option>{topics.map((topic) => <option key={topic.key} value={topic.key}>{topic.label}</option>)}</select></label>
          <label>종류 필터<select value={kind} onChange={(event) => resetFilter(() => setKind(event.target.value as RecordKind | ""))}><option value="">모든 종류</option>{recordKindOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</select></label>
          <label>보관 상태<select value={archived} onChange={(event) => resetFilter(() => setArchived(event.target.value as ArchivedFilter))}><option value="false">현재 기록</option><option value="true">보관 기록</option><option value="all">전체</option></select></label>
          <SelectField label="페이지당 표시" value={pageSize} onChange={(event) => {
            const option = learningPageSizeOptions.find(item => item.value === Number(event.target.value));
            if (option) resetFilter(() => setPageSize(option.value));
          }}>{learningPageSizeOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</SelectField>
        </div>
        {error ? <div className={styles.error} role="alert"><p>{error}</p><button type="button" onClick={load}>다시 시도</button></div> : null}
        {loading ? <p role="status">학습 기록을 불러오는 중…</p> : null}
        {!loading && !error && summaries.length === 0 ? <p className={styles.empty}>조건에 맞는 학습 기록이 없습니다.</p> : null}
        {!loading && !error && summaries.length > 0 ? (
          <LearningSequenceList records={summaries} topics={topics} ordered={sort !== "updated"} />
        ) : null}
        <Pagination label="학습 기록 페이지" position={`${cursorStack.length + 1}페이지`}
          canGoBack={!loading && cursorStack.length > 0} canGoForward={!loading && Boolean(result?.next_cursor)}
          onPrevious={() => {
            const previous = cursorStack.at(-1);
            setCursorStack(stack => stack.slice(0, -1));
            setCursor(previous);
          }}
          onNext={() => {
            setCursorStack(stack => [...stack, cursor]);
            setCursor(result?.next_cursor ?? undefined);
          }}
        />
      </section>
    </main>
  );
}

function newDraft(kind: RecordKind): LearningDraft {
  return { title: "", body: "", kind, topic_keys: [], domain_labels: [], experiment: kind === "experiment" ? emptyExperiment() : null, references: [] };
}
function errorMessage(error: unknown, fallback: string): string { return error instanceof Error && error.message ? error.message : fallback; }
function defaultCreated(record: LearningRecord) { window.location.assign(learningRecordPath(record.id)); }
