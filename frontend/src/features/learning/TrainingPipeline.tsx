import type { ReactNode } from "react";
import { Disclosure, StatusBadge } from "../../shared/ui/Feedback";
import { RecordBody } from "./RecordBody";
import { readTrainingPipeline } from "./trainingPipelineData";
import styles from "./TrainingPipeline.module.css";

type Stage = "input" | "target" | "training";

const stages = {
  input: { title: "입력", step: "01" },
  target: { title: "정답", step: "02" },
  training: { title: "학습", step: "03" },
};

function StageCard({ stage, children }: { stage: Stage; children: ReactNode }) {
  const { title, step } = stages[stage];
  return <li className={`${styles.card} ${styles[stage]}`}>
    <header className={styles.cardHeader}>
      <span className={styles.icon} aria-hidden="true">{stage === "target" &&
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
          <path d="M20 11a8 8 0 1 1-5-6.4M8 11.5l3 3L21 4.5" />
        </svg>}
      </span>
      <div><span className={styles.step}>STEP {step}</span><h3 className={styles.sectionTitle}>{title}</h3></div>
    </header>
    <div className={styles.fields}>{children}</div>
  </li>;
}

function EmphasizedRule({ text }: { text: string }) {
  return text.split(/(T\s*[+＋−-]\s*\d+(?:\s*영업일|일)?)/gi).map((part, index) =>
    index % 2 === 1 ? <strong key={index}>{part}</strong> : part);
}

interface PipelineProps {
  body: string;
  comparison?: { question: string; expected?: string } | null;
  procedure?: string | null;
}

export function TrainingPipeline({ body, comparison, procedure }: PipelineProps) {
  const data = readTrainingPipeline(body, comparison, procedure);
  if (!data) return <RecordBody body={body} />;
  // Only move trailing citation markers to the evidence field. Inline citations
  // can refer to individual claims and must stay next to those claims.
  const answer = data.expected.replace(/(?:\s*\[e\d+\])+\s*$/, "").trimEnd();
  return <div className={styles.root}>
    <ol className={styles.flow} aria-label="학습 단계" role="list">
      <StageCard stage="input">
        <div><p className={styles.fieldLabel}>입력 규정</p><p className={styles.rule}><EmphasizedRule text={data.rule} /></p></div>
        <div><p className={styles.fieldLabel}>사용자 질문</p><p className={styles.question}>{data.question}</p></div>
        {data.inputNote && <small>{data.inputNote}</small>}
      </StageCard>
      <StageCard stage="target">
        <div><p className={styles.fieldLabel}>기대 응답</p><p className={styles.answer}>{answer}</p></div>
        {(data.citations.length > 0 || data.referenceNote) && <div>
          <p className={styles.fieldLabel}>근거 참조</p>
          <div className={styles.evidence}>{data.citations.map(id => <StatusBadge key={id} tone="success">{id}</StatusBadge>)}
            {data.referenceNote && <span>{data.referenceNote}</span>}
          </div>
        </div>}
      </StageCard>
      <StageCard stage="training">
        <ul className={styles.actions} aria-label="학습 절차">{data.actions.map((action, index) => <li key={index}>
          <svg width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M2 8h10m-4-4 4 4-4 4" /></svg>
          <span>{action}</span></li>)}</ul>
        {data.facts.length > 0 && <dl className={styles.facts} aria-label="학습 핵심 정보">{data.facts.map(({ label, value }) =>
          <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}
      </StageCard>
    </ol>
    <Disclosure className={styles.original} summary="학습 원문 보기"><RecordBody body={body} /></Disclosure>
  </div>;
}
