import type { ReactNode } from "react";
import styles from "./Learning.module.css";

const stepPrefix = /^(\d{1,9})[.)](?=[ \t]+\S)/;
const trainingStep = /^([ \t]+)(입력|정답|학습)([ \t]*[—:：][ \t]*)(?=\S)/;
const stageStyles: Record<string, string> = {
  입력: styles.inputStage,
  정답: styles.targetStage,
  학습: styles.trainingStage,
};
const examplePrefix = /^예시(?:[ \t]*\([^()\r\n]+\))?[ \t]*[:：]/;
const fencePrefix = /^ {0,3}(`{3,}|~{3,})/;

export function RecordBody({ body }: { body: string }) {
  // Keep the original line endings, indentation and marker text for copying.
  const lines = body.match(/[^\r\n]*(?:\r\n|[\r\n])|[^\r\n]+$/g) ?? [];
  const blocks: ReactNode[] = [];
  let plainStart = 0;
  let index = 0;
  while (index < lines.length) {
    const start = index;
    const line = lines[index++];
    const fence = fencePrefix.exec(line)?.[1];
    if (fence) {
      while (index < lines.length) {
        const closing = /^ {0,3}(`+|~+)[ \t]*(?:\r\n|[\r\n])?$/.exec(lines[index++]);
        if (closing?.[1].startsWith(fence)) break;
      }
      continue;
    }

    const step = stepPrefix.exec(line);
    const example = examplePrefix.exec(line);
    if (step) {
      const first = Number(step[1]);
      const markers = [step[0]];
      while (index < lines.length) {
        const next = stepPrefix.exec(lines[index]);
        if (!next || Number(next[1]) !== first + markers.length) break;
        markers.push(next[0]);
        index++;
      }
      if (markers.length === 1) continue;
      blocks.push(lines.slice(plainStart, start).join(""));
      blocks.push(<ol className={styles.recordSteps} key={start} start={first} role="list">
        {markers.map((marker, offset) => {
          const content = lines[start + offset].slice(marker.length);
          const stage = trainingStep.exec(content);
          if (!stage) return <li key={start + offset}><span className={styles.stepNumber}>{marker}</span>{content}</li>;
          const [prefix, space, label, separator] = stage;
          return <li key={start + offset} className={`${styles.stageRow} ${stageStyles[label]}`}>
            <span className={styles.stageLabel}><span className={styles.stageNumber}>{marker}</span>{space}<strong>{label}</strong></span>
            <span className={styles.stageText}><span className={styles.stageSeparator} aria-hidden="true">{separator}</span>{content.slice(prefix.length)}</span>
          </li>;
        })}
      </ol>);
    } else if (example) {
      while (index < lines.length && /^\S/.test(lines[index]) && !examplePrefix.test(lines[index])
        && !stepPrefix.test(lines[index]) && !fencePrefix.test(lines[index])) index++;
      blocks.push(lines.slice(plainStart, start).join(""));
      blocks.push(<p className={styles.recordExample} key={start}><strong className={styles.exampleLabel}>{example[0]}</strong>{lines.slice(start, index).join("").slice(example[0].length)}</p>);
    } else {
      continue;
    }
    plainStart = index;
  }
  blocks.push(lines.slice(plainStart).join(""));
  return <div className={styles.recordBody}>{blocks}</div>;
}
