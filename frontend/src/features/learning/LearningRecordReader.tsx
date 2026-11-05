import Link from "next/link";
import type { ReactNode } from "react";
import { Disclosure } from "../../shared/ui/Feedback";

import type { EvaluationRun, LearningRecord, LearningSummary, ReferenceView } from "./api";
import styles from "./Learning.module.css";
import { RecordBody } from "./RecordBody";
import { AnswerComparisonView } from "./AnswerComparisonView";
import { TrainingPipeline } from "./TrainingPipeline";
import { readAnswerComparison } from "./answerComparison";
import { analyzeResult } from "./experimentResult";
import { ExperimentSettings, readExperimentSettings } from "./ExperimentSettings";
import { LearningSequenceDetail } from "./LearningSequence";

interface ReaderProps {
  record: LearningRecord;
  records: LearningSummary[];
  evaluations: EvaluationRun[];
}

function TextSection({ label, text, className }: { label: string; text?: string | null; className?: string }) {
  if (!text?.trim()) return null;
  return <section className={className}><h2>{label}</h2><RecordBody body={text} /></section>;
}

function TextList({ values }: { values: ReactNode[] }) {
  if (!values.length) return null;
  if (values.length === 1) return <p className={styles.singleItem}>{values[0]}</p>;
  return <ul>{values.map((value, index) => <li key={index}>{value}</li>)}</ul>;
}

type Detail = [string, ReactNode];

function Details({ label, entries }: { label: string; entries: Detail[] }) {
  const populated = entries.filter(([, value]) => value != null && value !== "");
  if (!populated.length) return null;
  return <section>
    <h2>{label}</h2>
    <dl>{populated.map(([name, value]) => <div key={name}>
      <dt>{name}</dt>
      <dd>{typeof value === "string" ? <RecordBody body={value} /> : value}</dd>
    </div>)}</dl>
  </section>;
}

export function LearningRecordReader({ record, records, evaluations }: ReaderProps) {
  const { draft } = record;
  const experiment = draft.experiment;
  const comparison = readAnswerComparison(experiment?.observations, draft.body);
  const result = comparison && analyzeResult(comparison);
  const settings = result ? readExperimentSettings(experiment?.procedure ?? "", result.conditions) : [];
  const trouble = experiment?.troubleshooting;
  const visibleReferences = record.reference_views.filter(view => view.status === "available");
  // The server resolves permissions per revision. Option lists may supply a label
  // only for a reference the server has explicitly marked available.
  function reference(view: ReferenceView) {
    if (view.status !== "available") return null;
    let label = view.label;
    if (!label && view.key?.kind === "learning.record") {
      label = records.find(item => item.id === view.key?.target)?.title ?? null;
    }
    if (!label && view.key?.kind === "rag.evaluation" && evaluations.some(item => item.id === view.key?.target)) {
      label = "RAG 평가";
    }
    label ||= "관련 자료";
    return view.href ? <Link href={view.href}>{label}</Link> : label;
  }

  return <div className={styles.reader}>
    {experiment?.learning_sequence && <LearningSequenceDetail value={experiment.learning_sequence} status={experiment.status} />}
    {comparison && experiment ? <>
      <TextSection label="학습 목적" text={experiment.purpose} className={styles.finding} />
      {draft.body.trim() && <section><h2>학습 내용과 방법</h2>
        <TrainingPipeline body={draft.body} comparison={comparison} procedure={experiment.procedure} />
      </section>}
      <AnswerComparisonView comparison={comparison} conclusion={experiment.conclusion} result={result ?? undefined} />
    </> : experiment && <>
      <TextSection label="결론" text={experiment.conclusion} className={styles.finding} />
      {!experiment.conclusion?.trim() && <TextSection label="실험 목적" text={experiment.purpose} className={styles.finding} />}
      <TextSection label="관찰" text={experiment.observations} />
    </>}
    {!comparison && draft.body.trim() && <section><h2>{experiment ? "학습 내용" : "본문"}</h2>
      {experiment ? <TrainingPipeline body={draft.body} procedure={experiment.procedure} /> : <RecordBody body={draft.body} />}
    </section>}
    {experiment && <>
      <Details label="실험 방법" entries={[
        ["목적", !comparison && experiment.conclusion?.trim() ? experiment.purpose : null], ["가설", experiment.hypothesis],
        ["데이터 snapshot", record.dataset_reference_view?.status === "unavailable" ? "접근할 수 없는 참조"
          : record.dataset_reference_view && reference(record.dataset_reference_view)],
        ["비교 구성", experiment.configurations.length ? <TextList values={experiment.configurations} /> : null],
        ["실행 환경", comparison && experiment.environment?.trim()
          ? <Disclosure summary="실행 환경 자세히 보기"><RecordBody body={experiment.environment} /></Disclosure>
          : experiment.environment],
        ["학습 설정", settings.length ? <ExperimentSettings entries={settings} /> : null],
        [comparison ? "학습 절차" : "절차", experiment.procedure],
        ["평가 조건", result?.conditions.length ? <TextList values={result.conditions} /> : null],
      ]} />
      <TextSection label="평가 범위와 한계" text={experiment.limitations?.trim() || (comparison ? "평가 범위가 기록되지 않았습니다." : null)} />
      {experiment.metrics.length > 0 && <section><h2>평가 지표</h2>
        <table aria-label="평가 지표"><thead><tr><th scope="col">지표</th><th scope="col">값</th><th scope="col">단위</th></tr></thead>
          <tbody>{experiment.metrics.map((metric, index) => <tr key={index}><th scope="row">{metric.name}</th><td>{metric.value}</td><td>{metric.unit ?? "—"}</td></tr>)}</tbody>
        </table></section>}
      {experiment.next_steps.length > 0 && <section><h2>다음 작업</h2><TextList values={experiment.next_steps} /></section>}
      {trouble && <Details label="문제 해결 기록" entries={[
        ["증상", trouble.symptom], ["재현 조건", trouble.reproduction],
        ["확인된 사실", trouble.facts.length ? <TextList values={trouble.facts} /> : null],
        ["원인 가설", trouble.hypotheses.length ? <TextList values={trouble.hypotheses} /> : null],
        ["확정 원인", trouble.confirmed_cause], ["변경 사항", trouble.change], ["재검증 결과", trouble.verification],
        ["미해결 항목", trouble.unresolved.length ? <TextList values={trouble.unresolved} /> : null],
      ]} />}
    </>}
    {(visibleReferences.length > 0 || record.unavailable_reference_count > 0) && <section>
      <h2>관련 참조</h2>
      <TextList values={visibleReferences.map(reference)} />
      {record.unavailable_reference_count > 0 && <p role="status" className={styles.warning}>접근할 수 없는 참조 {record.unavailable_reference_count}개</p>}
    </section>}
  </div>;
}
