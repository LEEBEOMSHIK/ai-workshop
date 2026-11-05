// Observations are plain text. Only promote a complete, labelled comparison.
const comparisonBlock = /^같은 질문의 실제 답변 비교\r?\n질문[ \t]+([^\r\n]+)\r?\n(?:학습 정답[ \t]+([^\r\n]+)\r?\n)?학습 전\(원본\)[ \t]+([^\r\n]+)\r?\n학습 후\(어댑터 적용\)[ \t]+([^\r\n]+)(?:\r?\n|$)/;

export function readAnswerComparison(observations?: string | null, body = "") {
  if (!observations) return null;
  const match = comparisonBlock.exec(observations);
  if (!match) return null;
  const [block, question, expected, before, after] = match;
  // Earlier records kept their labelled training target in the body.
  const bodyTarget = /^(?:학습 정답|학습에 사용한 정답)(?:[ \t]*[:：][ \t]*|[ \t]{2,})([^\r\n]+)$/m.exec(body);
  return { question, expected: expected ?? bodyTarget?.[1], before, after, notes: observations.slice(block.length).trimStart() };
}
