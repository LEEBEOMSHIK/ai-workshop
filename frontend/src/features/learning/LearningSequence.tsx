"use client";

import Link from "next/link";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { learningRecordPath } from "../../shared/routing/routes";
import { Disclosure, StatusBadge } from "../../shared/ui/Feedback";
import type { ExperimentFields, ExperimentStatus, LearningSummary, LearningTopic } from "./api";
import { experimentStatusOptions, learningOutcomeOptions, learningStartOptions, recordKindOptions } from "./registry";
import styles from "./LearningSequence.module.css";
import { resolveLearningConnections } from "./learningConnections";

type Sequence = NonNullable<ExperimentFields["learning_sequence"]>;

function stepLabel(sequence: Sequence | null | undefined, status: ExperimentStatus | null | undefined) {
  if (status === "planned") return "계획 · 미실행";
  return sequence?.step ? `${sequence.step}차 학습` : "차수 미기록";
}

function statusLabel(status: ExperimentStatus | null | undefined) {
  return experimentStatusOptions.find(option => option.value === status)?.label ?? "상태 미기록";
}

export function formatPerformedOn(value: string) {
  // A calendar date is independent of the browser's timezone.
  const [year, month, day] = value.split("-");
  return `${Number(year)}. ${Number(month)}. ${Number(day)}.`;
}

export function LearningSequenceDetail({ value, status }: { value: Sequence; status: ExperimentStatus }) {
  return <section className={styles.detail} aria-label="학습 순서">
    <div><span className={styles.caption}>학습 흐름</span><p className={styles.series}>{value.series}</p></div>
    <div className={styles.detailFacts}>
      <strong className={styles.stepLabel}>{stepLabel(value, status)}</strong>
      {status !== "planned" && <span className={styles.status} data-status={status}>{statusLabel(status)}</span>}
      {value.performed_on && status !== "planned" && <span>실행 <time dateTime={value.performed_on}>{formatPerformedOn(value.performed_on)}</time></span>}
      {!value.performed_on && status !== "planned" && <span>실행일 미기록</span>}
    </div>
    <LearningProgress value={value} planned={status === "planned"} showEvidence />
  </section>;
}

export function LearningSequenceList({ records, topics, ordered, startIndex = 0 }: { records: LearningSummary[]; topics: LearningTopic[]; ordered: boolean; startIndex?: number }) {
  const TitleHeading = ordered ? "h4" : "h3";
  const connections = useMemo(() => resolveLearningConnections(records), [records]);
  const listRef = useRef<HTMLDivElement>(null);
  const arrowId = useId();
  const [paths, setPaths] = useState<{ id: string; d: string }[]>([]);
  useEffect(() => {
    const root = listRef.current;
    if (!root) return;
    const measure = () => {
      const bounds = root.getBoundingClientRect();
      const markers = new Map(Array.from(root.querySelectorAll<HTMLElement>("[data-connection-anchor]")).map(marker => [marker.dataset.connectionAnchor!, marker.getBoundingClientRect()]));
      const lanes: { low: number; high: number }[][] = [[], [], [], []];
      const next: { id: string; d: string }[] = [];
      connections.forEach((connection, id) => {
        if (connection.status !== "connected") return;
        const source = markers.get(connection.sourceId);
        const target = markers.get(id);
        if (!source || !target || !source.height || !target.height) return;
        const sourceIndex = records.findIndex(record => record.id === connection.sourceId);
        const targetIndex = records.findIndex(record => record.id === id);
        if (Math.abs(sourceIndex - targetIndex) === 1) {
          const down = target.top > source.top;
          const x = source.left + source.width / 2 - bounds.left;
          next.push({ id, d: `M ${x} ${(down ? source.bottom : source.top) - bounds.top} V ${(down ? target.top - 3 : target.bottom + 3) - bounds.top}` });
          return;
        }
        const from = source.top + source.height / 2 - bounds.top;
        const to = target.top + target.height / 2 - bounds.top;
        const low = Math.min(from, to), high = Math.max(from, to);
        const lane = lanes.findIndex(intervals => intervals.every(interval => high <= interval.low || low >= interval.high));
        // Dense branching retains the explicit text relation instead of drawing ambiguous overlaps.
        if (lane < 0) return;
        lanes[lane].push({ low, high });
        const x = Math.min(source.left, target.left) - bounds.left - 22 + lane * 5;
        next.push({ id, d: `M ${source.left - bounds.left} ${from} H ${x} V ${to} H ${target.left - bounds.left - 3}` });
      });
      setPaths(next);
    };
    measure();
    const observer = typeof ResizeObserver !== "undefined" ? new ResizeObserver(measure) : null;
    observer?.observe(root);
    root.querySelectorAll("article, [data-connection-anchor]").forEach(element => observer?.observe(element));
    window.addEventListener("resize", measure);
    return () => { observer?.disconnect(); window.removeEventListener("resize", measure); };
  }, [connections, records]);
  return <div className={styles.sequenceCanvas} ref={listRef}>
    <p className={styles.sequenceLegend}>숫자는 목록 순번 · 가로선은 해당 기록 · 화살표는 이전 학습 → 후속 학습</p>
    <svg className={styles.connections} aria-hidden="true"><defs><marker id={arrowId} viewBox="0 0 6 6" refX="5" refY="3" markerWidth="5" markerHeight="5" orient="auto"><path d="M0 0L6 3L0 6" fill="currentColor" /></marker></defs>{paths.map(path => <path key={path.id} d={path.d} markerEnd={`url(#${arrowId})`} />)}</svg>
    <ol className={styles.list} aria-label="학습 기록 흐름">
    {records.map((record, index) => {
      const sequence = record.learning_sequence;
      const connection = connections.get(record.id);
      const status = record.experiment_status;
      const planned = status === "planned";
      const isExperiment = record.kind === "experiment";
      const newGroup = ordered && (index === 0 || sequence?.series !== records[index - 1]?.learning_sequence?.series);
      const startsPlans = planned && ordered && (newGroup || records[index - 1]?.experiment_status !== "planned");
      return <li key={record.id} className={styles.item}>
        {newGroup && <h3 className={styles.groupTitle}>{sequence?.series ?? "흐름 미지정 기록"}</h3>}
        {startsPlans && <p className={styles.planHeading}>관련 계획 · 실행 차수에 포함하지 않음</p>}
        <article className={styles.row} data-planned={planned || undefined}>
          <span className={styles.ordinal} data-connection-anchor={record.id} aria-label={`목록 순번 ${startIndex + index + 1}`}>{startIndex + index + 1}<span className={styles.cardStem} data-card-association={record.id} aria-hidden="true" /></span>
          <Link className={styles.content} href={learningRecordPath(record.id)} aria-labelledby={`learning-card-title-${record.id}`}>
            <div className={styles.rowMeta}>
              <div className={styles.states}>
                {isExperiment ? <strong className={styles.stepLabel}>{stepLabel(sequence, status)}</strong> : <span>자유 메모</span>}
                {isExperiment && !planned && <span className={styles.status} data-status={status ?? "unknown"}>{statusLabel(status)}</span>}
                {record.archived_at && <span>보관됨</span>}
              </div>
              <div className={styles.metaAside}>
              {isExperiment && !planned && <span className={styles.executionDate}>{sequence?.performed_on
                ? <time dateTime={sequence.performed_on}>실행 {formatPerformedOn(sequence.performed_on)}</time>
                : "실행일 미기록"}</span>}</div>
            </div>
            {isExperiment && !planned && <div className={styles.listRelation} role="group" aria-label="학습 출발 관계">
              <div className={styles.relationHeading}>
                <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M10 13a5 5 0 0 0 7 0l3-3a5 5 0 0 0-7-7l-2 2M14 11a5 5 0 0 0-7 0l-3 3a5 5 0 0 0 7 7l2-2" /></svg>
                {connection?.status === "connected" ? <span>{connection.sourceStep}차 학습 → {sequence?.step}차 학습 · 이어 학습</span>
                  : connection?.status === "outside" ? <span>{connection.sourceStep}차 학습에서 이어짐 · 현재 목록에 없음</span>
                  : <span><span>{sequence?.start_mode === "base_model" ? "원본 모델에서 시작" : sequence?.start_mode === "continued" && sequence.source_label?.trim() ? "이전 학습 결과에서 계속" : "출발점 미확인"}</span>{connection?.status === "unknown" && <> · <span>연결 미확인</span></>}</span>}
              </div>
              {sequence?.source_label?.trim() && <p className={styles.source}>{sequence.source_label}</p>}
            </div>}
            {!ordered && sequence?.series && <p className={styles.rowSeries}>{sequence.series}</p>}
            <TitleHeading className={styles.title} id={`learning-card-title-${record.id}`}>{record.title}</TitleHeading>
            <LearningRecordClassification topicKeys={record.topic_keys} topics={topics} kind={record.kind} />
            {isExperiment && <LearningProgress value={sequence} planned={planned} hideSource />}
            <div className={styles.footer}>
              <time dateTime={record.updated_at}>수정 {new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(record.updated_at))}</time>
            </div>
          </Link>
        </article>
      </li>;
    })}
  </ol></div>;
}

export function LearningRecordClassification({ topicKeys, topics, kind }: { topicKeys: string[]; topics: LearningTopic[]; kind: LearningSummary["kind"] }) {
  const label = topicKeys.length > 0 ? "기술 주제" : "기록 종류";
  const values = topicKeys.length > 0
    ? topicKeys.map(key => ({ key, label: topics.find(topic => topic.key === key)?.label ?? key }))
    : [{ key: kind, label: recordKindOptions.find(option => option.value === kind)?.label ?? kind }];
  return <div className={styles.classification} role="group" aria-label={label}>
    <span className={styles.caption}>{label}</span>
    <div className={styles.topicList}>{values.map(value => <StatusBadge key={value.key} tone="neutral" className={styles.topicBadge}>{value.label}</StatusBadge>)}</div>
  </div>;
}

function LearningProgress({ value, planned, showEvidence = false, hideSource = false }: { value?: Sequence | null; planned: boolean; showEvidence?: boolean; hideSource?: boolean }) {
  // A saved ordinal is not evidence of ancestry, and a missing evaluation is not success.
  const result = value?.outcome?.trim() ? value.outcome_status ?? "not_evaluated" : "not_evaluated";
  return <div className={styles.progress}>
    {!planned && !hideSource && <LearningSourceRelation value={value} />}
    <dl className={styles.progressFacts}>
      <div><dt>개선 목표</dt><dd>{value?.objective || "목표 미기록"}</dd></div>
      {!planned && <>
        <div><dt>확인된 결과</dt><dd>
          <span className={styles.outcome} data-outcome={result}>{learningOutcomeOptions.find(option => option.value === result)?.label ?? "미평가"}</span>
          {value?.outcome && <p>{value.outcome}</p>}
        </dd></div>
        <div><dt>남은 문제</dt><dd>{value?.remaining || "남은 문제 미기록"}</dd></div>
      </>}
    </dl>
    {showEvidence && !planned && value?.source_evidence && <Disclosure summary="출발점 확인 근거"><p className={styles.evidence}>{value.source_evidence}</p></Disclosure>}
  </div>;
}

function LearningSourceRelation({ value }: { value?: Sequence | null }) {
  const start = value?.start_mode === "continued" && !value.source_label?.trim() ? "unknown" : value?.start_mode ?? "unknown";
  const known = start === "continued" || start === "base_model";
  return <div className={styles.origin} role="group" aria-label="학습 출발 관계">
    <div className={styles.originHeading}>
      <span className={styles.caption}>학습 출발점</span>
      <strong>{learningStartOptions.find(option => option.value === start)?.label ?? "출발점 미확인"}</strong>
    </div>
    {known ? <div className={styles.sourceFlow}>
      <div className={styles.sourceNode}>
        <span className={styles.caption}>{start === "continued" ? "입력 학습 결과" : "기반 모델"}</span>
        <span>{value?.source_label?.trim() || "원본 모델"}</span>
      </div>
      <div className={styles.sourceConnector}>
        <span>{start === "continued" ? "이어 학습" : "새로 학습"}</span>
        <svg aria-hidden="true" viewBox="0 0 48 16" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M1 8h44m-6-6 6 6-6 6" /></svg>
      </div>
      <div className={styles.currentNode}>
        <span className={styles.caption}>이번 기록</span>
        <span>{value?.step ? `이번 ${value.step}차 학습` : "현재 학습 · 차수 미기록"}</span>
      </div>
    </div> : value?.source_label?.trim() && <p className={styles.source}>{value.source_label}</p>}
  </div>;
}
