import styles from "./ExperimentResult.module.css";

// Only lift explicitly named settings out of the recorded procedure/conditions.
// The full original text is rendered alongside these values by the reader.
const parameters: [string, RegExp][] = [
  ["기반 가중치", /기반 가중치\s+(BF16|FP32|FP16)\b/gi],
  ["LoRA 정밀도", /\b(BF16|FP32|FP16)\s+LoRA\b/gi],
  ["Rank", /\bLoRA\s+rank\s+(\d+)\b/gi],
  ["Seed", /\bseed\s+(\d+)\b/gi],
  ["배치 크기", /배치\s+(\d+)\b/g],
  ["옵티마이저", /(?:^|,\s*)(AdamW|Adam|SGD)(?=,|\.|$)/gi],
  ["학습률", /학습률\s+([\d.]+(?:e[-+]?\d+)?)(?=,|\s|$)/gi],
  ["Weight decay", /\bweight decay\s+(\d+(?:\.\d+)?(?:e[-+]?\d+)?)/gi],
  ["학습 스텝", /(?:^|,\s*)(\d+)\s*스텝(?=[.\s,]|$)/g],
];

export function readExperimentSettings(procedure: string, conditions: string[]) {
  const entries: [string, string][] = [];
  function add(label: string, pattern: RegExp, text: string) {
    const values = new Set(Array.from(text.matchAll(pattern), match => match[1]));
    if (values.size === 1) entries.push([label, [...values][0]]);
  }
  for (const [label, pattern] of parameters) add(label, pattern, procedure);
  add("응답 토큰 상한", /최대\s*(\d+)\s*토큰/g, conditions.join("\n"));
  return entries;
}

export function ExperimentSettings({ entries }: { entries: [string, string][] }) {
  return <ul className={styles.settings} aria-label="기록된 설정값">{entries.map(([label, value]) =>
    <li key={label}><span>{label}</span> <strong>{value}</strong></li>)}</ul>;
}
