import Link from "next/link";

import { learningRecordPath } from "../../shared/routing/routes";
import { Disclosure, StatusBadge } from "../../shared/ui/Feedback";
import type { ExperimentFields, ExperimentStatus, LearningSummary, LearningTopic } from "./api";
import { experimentStatusOptions, learningOutcomeOptions, learningStartOptions, recordKindOptions } from "./registry";
import styles from "./LearningSequence.module.css";

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

export function LearningSequenceList({ records, topics, ordered }: { records: LearningSummary[]; topics: LearningTopic[]; ordered: boolean }) {
  const TitleHeading = ordered ? "h4" : "h3";
  return <ol className={styles.list} aria-label="학습 기록 흐름">
    {records.map((record, index) => {
      const sequence = record.learning_sequence;
      const status = record.experiment_status;
      const planned = status === "planned";
      const isExperiment = record.kind === "experiment";
      const newGroup = ordered && (index === 0 || sequence?.series !== records[index - 1]?.learning_sequence?.series);
      const next = records[index + 1];
      const continues = ordered && !planned && Boolean(sequence?.step) && Boolean(next?.learning_sequence?.step)
        && next?.experiment_status !== "planned" && sequence?.series === next?.learning_sequence?.series;
      const startsPlans = planned && ordered && (newGroup || records[index - 1]?.experiment_status !== "planned");
      return <li key={record.id} className={styles.item}>
        {newGroup && <h3 className={styles.groupTitle}>{sequence?.series ?? "흐름 미지정 기록"}</h3>}
        {startsPlans && <p className={styles.planHeading}>관련 계획 · 실행 차수에 포함하지 않음</p>}
        <article className={styles.row} data-continues={continues || undefined} data-planned={planned || undefined}>
          <div className={styles.marker} aria-hidden="true">{!planned && sequence?.step && String(sequence.step).length <= 3 ? sequence.step : <SequenceIcon planned={planned} />}</div>
          <Link className={styles.content} href={learningRecordPath(record.id)} aria-labelledby={`learning-card-title-${record.id}`}>
            <div className={styles.rowMeta}>
              <div className={styles.states}>
                {isExperiment ? <strong className={styles.stepLabel}>{stepLabel(sequence, status)}</strong> : <span>자유 메모</span>}
                {isExperiment && !planned && <span className={styles.status} data-status={status ?? "unknown"}>{statusLabel(status)}</span>}
                {record.archived_at && <span>보관됨</span>}
              </div>
              {isExperiment && !planned && <span className={styles.executionDate}>{sequence?.performed_on
                ? <time dateTime={sequence.performed_on}>실행 {formatPerformedOn(sequence.performed_on)}</time>
                : "실행일 미기록"}</span>}
            </div>
            {!ordered && sequence?.series && <p className={styles.rowSeries}>{sequence.series}</p>}
            <TitleHeading className={styles.title} id={`learning-card-title-${record.id}`}>{record.title}</TitleHeading>
            <LearningRecordClassification topicKeys={record.topic_keys} topics={topics} kind={record.kind} />
            {isExperiment && <LearningProgress value={sequence} planned={planned} />}
            <div className={styles.footer}>
              <time dateTime={record.updated_at}>수정 {new Intl.DateTimeFormat("ko-KR", { dateStyle: "medium", timeStyle: "short" }).format(new Date(record.updated_at))}</time>
            </div>
          </Link>
        </article>
      </li>;
    })}
  </ol>;
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

function LearningProgress({ value, planned, showEvidence = false }: { value?: Sequence | null; planned: boolean; showEvidence?: boolean }) {
  // A saved ordinal is not evidence of ancestry, and a missing evaluation is not success.
  const start = value?.start_mode === "continued" && !value.source_label?.trim() ? "unknown" : value?.start_mode ?? "unknown";
  const result = value?.outcome?.trim() ? value.outcome_status ?? "not_evaluated" : "not_evaluated";
  return <div className={styles.progress}>
    {!planned && <div className={styles.origin}>
      <span className={styles.caption}>학습 출발점</span>
      <strong>{learningStartOptions.find(option => option.value === start)?.label ?? "출발점 미확인"}</strong>
      {value?.source_label && <span className={styles.source}>{value.source_label}</span>}
    </div>}
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

function SequenceIcon({ planned }: { planned: boolean }) {
  return <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
    {planned ? <><rect x="4" y="5" width="16" height="16" rx="3" /><path d="M8 3v4m8-4v4M4 10h16m-11 4h6m-6 3h4" /></> : <><path d="M7 3h7l4 4v14H7zM14 3v5h4M10 12h5m-5 4h5" /></>}
  </svg>;
}
