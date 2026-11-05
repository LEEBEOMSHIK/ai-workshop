import type { readAnswerComparison } from "./answerComparison";

export type SemanticVerdict = "correct" | "incorrect" | "unevaluated";
export type ResultTrend = "improved" | "regressed" | "unchanged" | "mixed" | "unevaluated";
export type Comparison = Omit<NonNullable<ReturnType<typeof readAnswerComparison>>, "expected"> & { expected?: string };
export interface AnswerAssessment {
  semantic: SemanticVerdict;
  cited: string[];
  missing: string[];
}

const assessmentLine = /^학습 (전|후) 의미 평가(?:[ \t]*[:：][ \t]*|[ \t]{2,})(정확|오답|미평가)$/;
const conditionLine = /^(?:비교|평가) 조건(?:[ \t]*[:：][ \t]*|[ \t]{2,})(\S.*)$/;

function verdict(values: Set<string>): SemanticVerdict {
  if (values.size === 1 && values.has("정확")) return "correct";
  if (values.size === 1 && values.has("오답")) return "incorrect";
  return "unevaluated";
}

function readObservations(notes: string) {
  const ratings = { before: new Set<string>(), after: new Set<string>() };
  const conditions: string[] = [];
  const remaining: { line: string; rating?: "before" | "after" }[] = [];
  let fence: string | undefined;
  for (const line of notes.match(/[^\r\n]*(?:\r\n|\r|\n)|[^\r\n]+$/g) ?? []) {
    const text = line.trimEnd();
    if (fence || /^ {0,3}(?:`{3,}|~{3,})/.test(text)) {
      const boundary = /^ {0,3}(`{3,}|~{3,})/.exec(text)?.[1];
      if (!fence) fence = boundary;
      else if (boundary?.startsWith(fence) && text.trim() === boundary) fence = undefined;
      remaining.push({ line });
      continue;
    }
    const rating = assessmentLine.exec(text);
    if (rating) {
      const phase = rating[1] === "전" ? "before" : "after";
      ratings[phase].add(rating[2]);
      remaining.push({ line, rating: phase });
      continue;
    }
    const condition = conditionLine.exec(text);
    if (condition) conditions.push(condition[1]);
    else remaining.push({ line });
  }
  // Conflicting ratings stay visible in the original notes.
  const unconsumed = remaining.filter(item => !item.rating || ratings[item.rating].size > 1);
  return { before: verdict(ratings.before), after: verdict(ratings.after), conditions, notes: unconsumed.map(item => item.line).join("").replace(/(?:\r\n|\r|\n)+$/, "") };
}

function citations(answer: string) {
  const ids = new Set<string>();
  // Validate the whole bracket group; never infer IDs from prose or ranges.
  for (const [, group] of answer.matchAll(/\[([^\]\r\n]*)\]/g)) {
    if (!/^[ \t]*e\d+(?:[ \t]*,[ \t]*e\d+)*[ \t]*$/.test(group)) continue;
    for (const id of group.split(",")) ids.add(`[${id.trim()}]`);
  }
  return [...ids];
}

function assess(answer: string, required: string[], semantic: SemanticVerdict): AnswerAssessment {
  const cited = citations(answer);
  return { semantic, cited, missing: required.filter(id => !cited.includes(id)) };
}

function semanticChange(before: SemanticVerdict, after: SemanticVerdict): ResultTrend {
  if (before === "unevaluated" || after === "unevaluated") return "unevaluated";
  if (before === after) return "unchanged";
  return after === "correct" ? "improved" : "regressed";
}

function citationChange(required: string[], added: string[], lost: string[]): ResultTrend {
  if (!required.length) return "unevaluated";
  if (added.length && lost.length) return "mixed";
  if (added.length) return "improved";
  if (lost.length) return "regressed";
  return "unchanged";
}

export function analyzeResult(comparison: Comparison) {
  const observations = readObservations(comparison.notes);
  const required = citations(comparison.expected ?? "");
  const before = assess(comparison.before, required, observations.before);
  const after = assess(comparison.after, required, observations.after);
  const added = before.missing.filter(id => !after.missing.includes(id));
  const lost = after.missing.filter(id => !before.missing.includes(id));
  return {
    sameText: comparison.before.trim() === comparison.after.trim(),
    required, before, after, added, lost,
    citationTrend: citationChange(required, added, lost),
    semanticTrend: semanticChange(before.semantic, after.semantic),
    conditions: observations.conditions,
    notes: observations.notes,
  };
}
