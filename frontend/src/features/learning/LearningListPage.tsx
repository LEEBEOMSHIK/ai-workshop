"use client";

import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { learningRecordPath } from "../../shared/routing/routes";
import { Pagination } from "../../shared/ui/Pagination";
import { SelectField } from "../../shared/ui/Fields";
import { Button } from "../../shared/ui/Button";
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
  const filterPanelId = useId();
  const [filtersOpen, setFiltersOpen] = useState(false);
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
  const activeFilterCount = Number(Boolean(topicKey)) + Number(Boolean(kind)) + Number(archived !== "false");
  const archiveLabel = archived === "all" ? "현재·보관 기록" : archived === "true" ? "보관 기록" : "현재 기록";
  const draftSeed = useMemo(() => newKind ? newDraft(newKind) : null, [newKind]);
  return (
    <main className={`${styles.shell} ${styles.listShell}`}>
      <header className={styles.listHeader}>
        <div>
          <h1>학습 기록</h1>
          <p>배운 내용과 실험 과정을 기록하고 이어갑니다.</p>
        </div>
        <Button variant="primary" onClick={() => beginNew("note")}>
          <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round"><path d="M12 5v14M5 12h14" /></svg>
          새 기록
        </Button>
      </header>

      {newKind && draftSeed ? (
        <section className={styles.panel} aria-labelledby="new-record-heading">
          <div className={styles.sectionHeading}>
            <h2 id="new-record-heading">새 기록</h2>
            <button type="button" onClick={() => transitionNewDraft(null)}>작성 닫기</button>
          </div>
          <p className={styles.sequenceHint}>자유롭게 기록하고, 필요하면 작성 중에 실험 항목을 추가하세요.</p>
          <p className={styles.sequenceHint}>학습 기록을 저장해도 모델 학습, 외부 전송 또는 공개가 실행되지는 않습니다.</p>
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

      <section className={styles.recordList} aria-label="학습 기록 목록">
        <div className={styles.listHeading}>
          <div className={styles.filterSummary} role="group" aria-label="적용된 필터">
            <span>{archiveLabel}</span>
            {topicKey && <span className={styles.filterChip}>{topics.find(topic => topic.key === topicKey)?.label ?? topicKey}</span>}
            {kind && <span className={styles.filterChip}>{recordKindOptions.find(option => option.value === kind)?.label ?? kind}</span>}
            {activeFilterCount > 0 && <Button variant="quiet" onClick={() => resetFilter(() => { setTopicKey(""); setKind(""); setArchived("false"); })}>필터 초기화</Button>}
          </div>
          <div className={styles.listToolbar}>
            <SelectField label="정렬" value={sort} onChange={(event) => resetFilter(() => setSort(event.target.value as typeof sort))}>
              <option value="learning_latest">학습 흐름별 최신순</option><option value="learning_order">학습 흐름별 처음부터</option><option value="updated">최근 수정순</option>
            </SelectField>
            <Button variant="quiet" className={styles.filterToggle} aria-expanded={filtersOpen} aria-controls={filterPanelId} onClick={() => setFiltersOpen(open => !open)}>
              <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="M4 7h16M4 17h16" /><circle cx="9" cy="7" r="3" fill="var(--color-background)" /><circle cx="15" cy="17" r="3" fill="var(--color-background)" /></svg>
              상세 필터{activeFilterCount > 0 && <span className={styles.filterCount}>{activeFilterCount}</span>}
              <svg className={styles.filterChevron} aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><path d="m6 9 6 6 6-6" /></svg>
            </Button>
          </div>
        </div>
        <div id={filterPanelId} hidden={!filtersOpen} className={styles.filterPanel}>
          <div className={styles.detailFilters}>
            <SelectField label="주제 필터" value={topicKey} onChange={(event) => resetFilter(() => setTopicKey(event.target.value))}><option value="">모든 주제</option>{topics.map((topic) => <option key={topic.key} value={topic.key}>{topic.label}</option>)}</SelectField>
            <SelectField label="종류 필터" value={kind} onChange={(event) => resetFilter(() => setKind(event.target.value as RecordKind | ""))}><option value="">모든 종류</option>{recordKindOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}</SelectField>
            <SelectField label="보관 상태" value={archived} onChange={(event) => resetFilter(() => setArchived(event.target.value as ArchivedFilter))}><option value="false">현재 기록</option><option value="true">보관 기록</option><option value="all">전체</option></SelectField>
          </div>
        </div>
        {error ? <div className={styles.error} role="alert"><p>{error}</p><Button onClick={load}>다시 시도</Button></div> : null}
        {loading ? <p role="status">학습 기록을 불러오는 중…</p> : null}
        {!loading && !error && summaries.length === 0 ? <p className={styles.empty}>조건에 맞는 학습 기록이 없습니다.</p> : null}
        {!loading && !error && summaries.length > 0 ? (
          <LearningSequenceList records={summaries} topics={topics} ordered={sort !== "updated"} startIndex={cursorStack.length * pageSize} />
        ) : null}
        <div className={styles.listFooter}>
          <SelectField label="페이지당 표시" value={pageSize} onChange={(event) => {
            const option = learningPageSizeOptions.find(item => item.value === Number(event.target.value));
            if (option) resetFilter(() => setPageSize(option.value));
          }}>{learningPageSizeOptions.map(option => <option key={option.value} value={option.value}>{option.label}</option>)}</SelectField>
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
        </div>
      </section>
    </main>
  );
}

function newDraft(kind: RecordKind): LearningDraft {
  return { title: "", body: "", kind, topic_keys: [], domain_labels: [], experiment: kind === "experiment" ? emptyExperiment() : null, references: [] };
}
function errorMessage(error: unknown, fallback: string): string { return error instanceof Error && error.message ? error.message : fallback; }
function defaultCreated(record: LearningRecord) { window.location.assign(learningRecordPath(record.id)); }
