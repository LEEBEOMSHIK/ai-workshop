export interface TrainingPipelineData {
  rule: string;
  question: string;
  expected: string;
  citations: string[];
  referenceNote: string;
  actions: string[];
  facts: { label: string; value: string }[];
  inputNote: string;
}

type ComparisonExample = { question: string; expected?: string };

// Only promote an entire, explicitly ordered set of training stages. Other
// notes, including fenced examples and incomplete drafts, keep their reader.
const stages = /^1[.)]\s+입력\s*[—:：]\s*([^\n]+)\n2[.)]\s+정답\s*[—:：]\s*([^\n]+)\n3[.)]\s+학습\s*[—:：]\s*([^\n]+)$/;

function readQuotes(text: string) {
  return Array.from(text.matchAll(/“([^”]+)”|"([^"]+)"/g), match => ({
    value: (match[1] ?? match[2]).trim(),
    start: match.index,
    end: match.index + match[0].length,
  }));
}

function readActions(training: string) {
  // Keep the author's words when a clause is not in one of the compact forms.
  const clauses = training.split(/(?<=[.!?])\s+|(?<=고),\s+|(?<=한 채)\s+/u);
  return clauses.map(clause => clause
    .replace(/^모델이 (.+)하도록 했다[.]?$/, "$1")
    .replace(/^(.+?)(?:을|를) 계산하고$/, "$1 계산")
    .replace(/^(.+?)(?:은|는|을|를) 고정한 채$/, "$1 고정")
    .replace(/^(.+?)\(([^()]+)\)만 (.+?) 갱신했다[.]?$/, "$2만 $3 갱신")
    .trim()).filter(Boolean);
}

function readFacts(training: string, procedure: string) {
  const facts: TrainingPipelineData["facts"] = [];
  if (/정답[^.!?\n]*예측하도록 했다/.test(training)
    && /정답[^.!?\n]*에만 손실을 계산했다/.test(procedure)) {
    facts.push({ label: "학습 방식", value: "지도 미세조정 (SFT)" });
  }
  const update = /(?:\(([^()\n]+)\)|([\w가-힣-]+ 어댑터))(?:만|를|을)\s+(한\s*번|두\s*번|세\s*번|\d+\s*(?:회|번))\s*갱신했다(?:[.]|$)/.exec(training);
  if (update) {
    const counts: Record<string, string> = { 한: "1", 두: "2", 세: "3" };
    const count = update[3].replace(/\s*(번|회)$/, "").trim();
    facts.push({ label: "학습 대상", value: update[1] ?? update[2] });
    facts.push({ label: "업데이트 횟수", value: (counts[count] ?? count) + "회" });
  }
  return facts;
}

export function readTrainingPipeline(
  body: string,
  comparison?: ComparisonExample | null,
  procedure?: string | null,
): TrainingPipelineData | null {
  const match = stages.exec(body.trim().replace(/\r\n?/g, "\n"));
  if (!match) return null;
  const [, input, target, training] = match;
  const inputQuotes = readQuotes(input);
  const targetQuotes = readQuotes(target);
  const rule = inputQuotes[0];
  const question = inputQuotes[1]?.value ?? comparison?.question;
  const expected = targetQuotes[0]?.value ?? comparison?.expected;
  if (!rule || !question || !expected || rule.value === question || inputQuotes.length > 2
    || targetQuotes.length > 1 || (comparison && question !== comparison.question)
    || (comparison?.expected && expected !== comparison.expected)) return null;

  const targetTail = targetQuotes[0] ? target.slice(targetQuotes[0].end) : target;
  return {
    rule: rule.value,
    question,
    expected,
    citations: [...new Set(expected.match(/\[e\d+\]/g) ?? [])],
    referenceNote: targetTail.replace(/^\s*(?:을|를)?\s*정답으로 주었다[.]?\s*/, "").trim(),
    actions: readActions(training),
    facts: readFacts(training, procedure ?? ""),
    inputNote: input.slice(0, rule.start).trim(),
  };
}
