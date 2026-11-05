import { Disclosure, StatusBadge, type FeedbackTone } from "../../shared/ui/Feedback";
import { analyzeResult } from "./experimentResult";
import styles from "./ExperimentResult.module.css";
import { RecordBody } from "./RecordBody";

type Comparison = Parameters<typeof analyzeResult>[0];
type Assessment = ReturnType<typeof analyzeResult>;
type Signal = { text: string; tone: FeedbackTone };
const pending: Signal = { text: "미평가", tone: "neutral" };

function meaning(value: Assessment["after"]["semantic"]): Signal {
  if (value === "correct") return { text: "정확", tone: "success" };
  if (value === "incorrect") return { text: "오답", tone: "danger" };
  return pending;
}

function citationSignal(result: Assessment): Signal | null {
  const { citationTrend, after } = result;
  if (citationTrend === "mixed") return { text: "근거 인용 일부 변경", tone: "warning" };
  if (citationTrend === "improved") return { text: "근거 인용 추가", tone: "success" };
  if (citationTrend === "regressed") return { text: "근거 인용 감소", tone: "danger" };
  if (!after.missing.length) return null;
  const subject = after.missing.length === 1 ? after.missing[0] : `근거 ${after.missing.length}개`;
  return { text: `${subject} 전후 모두 누락`, tone: "warning" };
}

function QuestionIcon() {
  return <svg aria-hidden="true" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
    <path d="M4 4h16v13h-8l-5 4v-4H4zM10 8a2 2 0 1 1 3 1.7c-.8.5-1 1-1 1.8m0 2v.1" />
  </svg>;
}

function AnswerCard({ title, caption, text, row, required, changes }: {
  title: string; caption: string; text?: string; row?: Assessment["after"]; required: string[]; changes?: Assessment;
}) {
  const cited = row ? row.cited : required;
  const semantic = row && meaning(row.semantic);
  const detail = changes && required.length > 1 && (changes.added.length > 0 || changes.lost.length > 0);
  const stillMissing = detail ? row?.missing.filter(id => !changes.lost.includes(id)) ?? [] : [];
  return <article aria-label={title} className={`${styles.answer} ${row ? "" : styles.reference}`}>
    <div className={styles.answerHeader}><small lang="en">{caption}</small><h3>{title}</h3></div>
    <p className={styles.answerText}>{text ?? "기록된 정답 없음"}</p>
    <div className={styles.rowMeta}>
      {semantic && <StatusBadge tone={semantic.tone}>의미 평가 · {semantic.text}</StatusBadge>}
      {cited.length > 0 && <span>{row ? "포함된 번호" : "기준 인용"} {cited.join(" ")}</span>}
      {!detail && row && row.missing.length > 0 && <StatusBadge tone="warning">누락 {row.missing.join(" ")}</StatusBadge>}
      {!required.length && <span>인용 기준 미기록</span>}
    </div>
    {detail && <div className={styles.citationChanges} role="group" aria-label="인용 변화">
      {changes.added.length > 0 && <StatusBadge tone="success">{changes.added.join(" ")} 새로 포함</StatusBadge>}
      {changes.lost.length > 0 && <StatusBadge tone="danger">{changes.lost.join(" ")} 학습 후 누락</StatusBadge>}
      {stillMissing.length > 0 && <StatusBadge tone="warning">{stillMissing.join(" ")} 계속 누락</StatusBadge>}
    </div>}
  </article>;
}

export function AnswerComparisonView({ comparison, conclusion, result = analyzeResult(comparison) }: {
  comparison: Comparison; conclusion?: string | null; result?: Assessment;
}) {
  const citation = citationSignal(result);
  return <section className={styles.root}>
    <h2>학습 전후 답변 비교</h2>
    <div className={styles.summary} role="group" aria-label="결과 요약">
      <StatusBadge>{result.sameText ? "답변 변화 없음" : "답변 문구 변경"}</StatusBadge>
      {citation && <StatusBadge tone={citation.tone}>{citation.text}</StatusBadge>}
    </div>
    <div className={styles.question}><QuestionIcon /><div><small lang="en">TEST QUESTION</small><p>{comparison.question}</p></div></div>
    <div className={styles.answers}>
      <AnswerCard caption="Reference" title="학습 정답" text={comparison.expected} required={result.required} />
      <AnswerCard caption="Before" title="학습 전" text={comparison.before} row={result.before} required={result.required} />
      <AnswerCard caption="After" title="학습 후" text={comparison.after} row={result.after} required={result.required} changes={result} />
    </div>
    {(conclusion?.trim() || result.notes) && <section className={styles.conclusion}><h3>실험 결론</h3>
      {conclusion?.trim() ? <><RecordBody body={conclusion} />{result.notes && <Disclosure summary="상세 관찰 보기"><RecordBody body={result.notes} /></Disclosure>}</> : <RecordBody body={result.notes} />}
    </section>}
  </section>;
}
